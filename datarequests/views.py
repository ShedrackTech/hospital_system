from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import FormView, ListView

from cases import permissions as case_perms
from core import audit

from . import permissions as perms
from . import services
from .forms import FilterForm, HandleForm, RequestForm
from .models import DataRequest

OPEN_STATUSES = ["open", "in_review"]


class PatientOnlyMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        user = request.user
        if user.is_authenticated and not (user.is_patient and case_perms.get_patient(user)):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class HandlerRequiredMixin(LoginRequiredMixin):
    """Admin roles and records officers only."""

    def dispatch(self, request, *args, **kwargs):
        user = request.user
        if user.is_authenticated and not perms.can_handle(user):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class MyRequestsView(PatientOnlyMixin, View):
    def get(self, request):
        patient = case_perms.get_patient(request.user)
        return render(request, "datarequests/mine.html", {
            "requests": DataRequest.objects.filter(patient=patient),
        })


class NewRequestView(PatientOnlyMixin, FormView):
    template_name = "datarequests/form.html"
    form_class = RequestForm

    def form_valid(self, form):
        patient = case_perms.get_patient(self.request.user)
        try:
            data_request = services.create_request(
                patient, form.cleaned_data["kind"], form.cleaned_data["subject"],
                form.cleaned_data["details"], request=self.request,
            )
        except ValidationError as error:
            form.add_error(None, error)
            return self.form_invalid(form)
        messages.success(self.request, "Your request has been received.")
        return redirect("datarequests:detail", pk=data_request.pk)


def get_request_for(user, pk):
    data_request = get_object_or_404(DataRequest.objects.select_related("patient__user"), pk=pk)
    if user.is_patient:
        if data_request.patient.user_id != user.id:
            raise Http404
    elif not perms.can_handle(user):
        raise Http404
    return data_request


class RequestDetailView(LoginRequiredMixin, View):
    def get(self, request, pk):
        data_request = get_request_for(request.user, pk)
        is_admin = not request.user.is_patient
        if is_admin:  # a staff member reading a patient's request is audited
            audit.log(request.user, "data_request_viewed", data_request,
                      patient=data_request.patient, request=request)
        return render(request, "datarequests/detail.html", {
            "data_request": data_request,
            "is_admin_view": is_admin,
            "handle_form": HandleForm(initial={"response": data_request.response})
            if is_admin and not data_request.is_closed else None,
        })


class RequestHandleView(HandlerRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        data_request = get_request_for(request.user, pk)
        form = HandleForm(request.POST)
        if form.is_valid():
            try:
                services.update_request(
                    request.user, data_request, form.cleaned_data["status"],
                    form.cleaned_data["response"], request=request,
                )
                messages.success(request, "Request updated.")
            except ValidationError as error:
                messages.error(request, " ".join(error.messages))
        else:
            messages.error(request, "Please check the form and try again.")
        return redirect("datarequests:detail", pk=pk)


class ManageListView(HandlerRequiredMixin, ListView):
    template_name = "datarequests/manage.html"
    context_object_name = "requests"
    paginate_by = 25

    def get_queryset(self):
        self.form = FilterForm(self.request.GET)
        requests = DataRequest.objects.select_related("patient__user")
        data = self.form.cleaned_data if self.form.is_valid() else {}
        status = data.get("status", "")
        if status == "":
            requests = requests.filter(status__in=OPEN_STATUSES)
        elif status != "all":
            requests = requests.filter(status=status)
        if data.get("kind"):
            requests = requests.filter(kind=data["kind"])
        query = (data.get("q") or "").strip()
        if query:
            requests = requests.filter(
                Q(subject__icontains=query) | Q(patient__user__login_id__icontains=query)
                | Q(patient__user__first_name__icontains=query)
                | Q(patient__user__last_name__icontains=query)
            )
        return requests.order_by("created_at")  # oldest first: they have waited longest

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["form"] = self.form
        params = self.request.GET.copy()
        params.pop("page", None)
        context["query_string"] = params.urlencode()
        return context
