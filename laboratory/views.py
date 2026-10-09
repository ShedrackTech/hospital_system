from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import CreateView, FormView, ListView, UpdateView

from cases import permissions as case_perms
from cases.models import Case
from core import audit

from . import permissions as perms
from . import services
from .forms import CancelForm, EnterResultForm, LabTestForm, OrderForm
from .models import LabResult, LabTest

RESULT_QS = LabResult.objects.select_related(
    "case__department", "case__patient__user", "patient__user", "test",
    "ordered_by", "entered_by", "released_by",
)


class LabAreaMixin(LoginRequiredMixin):
    """Laboratory staff and admin roles only."""

    def dispatch(self, request, *args, **kwargs):
        user = request.user
        if user.is_authenticated and not (
            perms.is_lab_staff(user) or case_perms.is_admin(user)
        ):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class FormPageMixin:
    template_name = "laboratory/form.html"
    page_title = ""
    submit_label = "Save"
    cancel_url = None

    def get_cancel_url(self):
        return self.cancel_url or reverse("laboratory:tests")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_title=self.page_title, submit_label=self.submit_label,
                       cancel_url=self.get_cancel_url())
        return context


# ---- Test catalogue ----

class TestListView(LabAreaMixin, ListView):
    template_name = "laboratory/test_list.html"
    context_object_name = "tests"
    queryset = LabTest.objects.all()


class TestCreateView(LabAreaMixin, FormPageMixin, CreateView):
    form_class = LabTestForm
    page_title = "New lab test"

    def form_valid(self, form):
        response = super().form_valid(form)
        audit.log(self.request.user, "lab_test_created", self.object, request=self.request)
        messages.success(self.request, "Test added to the catalogue.")
        return response

    def get_success_url(self):
        return reverse("laboratory:tests")


class TestUpdateView(LabAreaMixin, FormPageMixin, UpdateView):
    form_class = LabTestForm
    queryset = LabTest.objects.all()

    @property
    def page_title(self):
        return f"Edit {self.object.name}"

    def form_valid(self, form):
        response = super().form_valid(form)
        audit.log(self.request.user, "lab_test_updated", self.object, request=self.request)
        messages.success(self.request, "Test updated.")
        return response

    def get_success_url(self):
        return reverse("laboratory:tests")


# ---- Worklist (lab staff and admin) ----

class WorklistView(LabAreaMixin, ListView):
    template_name = "laboratory/worklist.html"
    context_object_name = "results"
    paginate_by = 25

    def get_queryset(self):
        status = self.request.GET.get("status", "open")
        results = RESULT_QS
        if status == "open":
            results = results.filter(status__in=["ordered", "resulted"])
        elif status in dict(LabResult.Status.choices):
            results = results.filter(status=status)
        self.status = status
        return results.order_by("ordered_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["status"] = self.status
        context["statuses"] = LabResult.Status.choices
        return context


# ---- Ordering (assigned doctor or department head) ----

class OrderView(LoginRequiredMixin, FormPageMixin, FormView):
    form_class = OrderForm
    submit_label = "Order tests"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        self.case = get_object_or_404(
            Case.objects.select_related("patient__user", "department"), pk=kwargs["case_pk"]
        )
        if not case_perms.can_view(request.user, self.case):
            raise Http404
        if not perms.can_order(request.user, self.case):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    @property
    def page_title(self):
        return f"Order lab tests for case #{self.case.pk}"

    def get_cancel_url(self):
        return reverse("cases:detail", args=[self.case.pk])

    def form_valid(self, form):
        try:
            services.order_tests(
                self.case, form.cleaned_data["tests"], self.request.user,
                form.cleaned_data["note"], request=self.request,
            )
        except ValidationError as error:
            form.add_error(None, error)
            return self.form_invalid(form)
        messages.success(self.request, "Tests ordered.")
        return redirect("cases:detail", pk=self.case.pk)


# ---- A single result ----

def get_result_for(user, pk):
    result = get_object_or_404(RESULT_QS, pk=pk)
    if not perms.can_view(user, result):
        raise Http404  # do not reveal that it exists
    return result


class ResultDetailView(LoginRequiredMixin, View):
    def get(self, request, pk):
        result = get_result_for(request.user, pk)
        u = request.user
        if not u.is_patient:  # staff access to a result is audited
            audit.log(u, "lab_result_viewed", result, patient=result.patient, request=request)
        return render(request, "laboratory/result_detail.html", {
            "result": result,
            "enter_form": EnterResultForm() if perms.can_enter(u, result) else None,
            "cancel_form": CancelForm() if perms.can_cancel(u, result) else None,
            "can_release": perms.can_release(u, result),
            "can_print": perms.can_print(u, result),
            "is_patient_view": u.is_patient,
        })


class ResultActionView(LoginRequiredMixin, View):
    """POST-only base: permission check, validate form, call the service."""

    http_method_names = ["post"]
    form_class = None
    success_text = "Updated."

    def check(self, user, result):
        raise NotImplementedError

    def run(self, request, result, form):
        raise NotImplementedError

    def post(self, request, pk):
        result = get_result_for(request.user, pk)
        if not self.check(request.user, result):
            raise PermissionDenied
        form = self.form_class(request.POST) if self.form_class else None
        if form is not None and not form.is_valid():
            messages.error(request, "Please check the form and try again.")
        else:
            try:
                self.run(request, result, form)
                messages.success(request, self.success_text)
            except ValidationError as error:
                messages.error(request, " ".join(error.messages))
        return redirect("laboratory:result", pk=result.pk)


class ResultEnterView(ResultActionView):
    form_class = EnterResultForm
    success_text = "Result saved. It must be released before the patient can see it."
    check = staticmethod(perms.can_enter)

    def run(self, request, result, form):
        services.enter_result(result, form.cleaned_data["value"],
                              form.cleaned_data["notes"], request.user, request=request)


class ResultReleaseView(ResultActionView):
    success_text = "Result released to the patient."
    check = staticmethod(perms.can_release)

    def run(self, request, result, form):
        services.release_result(result, request.user, request=request)


class ResultCancelView(ResultActionView):
    form_class = CancelForm
    success_text = "Test cancelled."
    check = staticmethod(perms.can_cancel)

    def run(self, request, result, form):
        services.cancel_result(result, request.user, form.cleaned_data["reason"],
                               request=request)


class ResultPrintView(LoginRequiredMixin, View):
    """A clean page the patient (or staff) prints or saves as PDF from the browser."""

    def get(self, request, pk):
        result = get_result_for(request.user, pk)
        if not perms.can_print(request.user, result):
            raise PermissionDenied  # only released results can be printed
        audit.log(request.user, "lab_result_printed", result, patient=result.patient,
                  request=request)
        return render(request, "laboratory/print.html", {
            "result": result,
            "hospital_name": getattr(settings, "HOSPITAL_NAME", "Hospital"),
        })


# ---- Patient's own released results ----

class MyResultsView(LoginRequiredMixin, View):
    def get(self, request):
        patient = case_perms.get_patient(request.user)
        if not request.user.is_patient or patient is None:
            raise PermissionDenied
        results = (
            LabResult.objects.filter(patient=patient, status=LabResult.Status.RELEASED)
            .select_related("test").order_by("-released_at")
        )
        return render(request, "laboratory/my_results.html", {"results": results})
