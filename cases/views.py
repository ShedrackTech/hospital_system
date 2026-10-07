from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import redirect, render
from django.views import View

from . import permissions as perms
from . import services
from .forms import AssignForm, CaseCreateForm, RouteForm, StatusForm
from .models import Case

BASE_QS = Case.objects.select_related("patient", "department", "assigned_to")


class RoleListView(LoginRequiredMixin, UserPassesTestMixin, View):
    """Base for list pages. Subclasses define allowed(), get_queryset(), title."""
    title = "Cases"

    def allowed(self, user):
        return True

    def test_func(self):
        return self.allowed(self.request.user)

    def get_queryset(self):
        raise NotImplementedError

    def get(self, request):
        qs = self.get_queryset()
        status = request.GET.get("status")
        if status in dict(Case.Status.choices):
            qs = qs.filter(status=status)
        return render(request, "cases/case_list.html", {
            "cases": qs, "title": self.title,
            "statuses": Case.Status.choices, "current_status": status,
        })


class CaseHomeView(LoginRequiredMixin, View):
    def get(self, request):
        u = request.user
        if perms.is_admin(u):
            return redirect("cases:all")
        if perms.headed_department(u):
            return redirect("cases:department")
        if perms.is_general_staff(u):
            return redirect("cases:triage")
        if perms.is_medical(u):
            return redirect("cases:assigned")
        if perms.get_patient(u):
            return redirect("cases:mine")
        raise PermissionDenied


class MyCasesView(RoleListView):
    title = "My cases"

    def allowed(self, user):
        return perms.get_patient(user) is not None

    def get_queryset(self):
        return BASE_QS.filter(patient__user=self.request.user)


class TriageQueueView(RoleListView):
    title = "Triage queue: cases waiting to be routed"

    def allowed(self, user):
        return perms.is_general_staff(user) or perms.is_admin(user)

    def get_queryset(self):
        return BASE_QS.filter(status=Case.Status.PENDING, routed_at__isnull=True)


class DepartmentQueueView(RoleListView):
    title = "Department cases"

    def allowed(self, user):
        return perms.headed_department(user) is not None

    def get_queryset(self):
        dept = perms.headed_department(self.request.user)
        return BASE_QS.filter(department=dept, routed_at__isnull=False)


class AssignedCasesView(RoleListView):
    title = "My assigned cases"

    def allowed(self, user):
        return perms.is_medical(user)

    def get_queryset(self):
        return BASE_QS.filter(assigned_to=self.request.user)


class AllCasesView(RoleListView):
    title = "All cases"

    def allowed(self, user):
        return perms.is_admin(user)

    def get_queryset(self):
        return BASE_QS.all()


class CaseCreateView(LoginRequiredMixin, View):
    def _patient(self, request):
        patient = perms.get_patient(request.user)
        if patient is None:
            raise PermissionDenied
        return patient

    def get(self, request):
        self._patient(request)
        return render(request, "cases/case_form.html", {"form": CaseCreateForm()})

    def post(self, request):
        patient = self._patient(request)
        form = CaseCreateForm(request.POST)
        if form.is_valid():
            case = services.create_case(
                patient, form.cleaned_data["complaint"],
                form.cleaned_data["department"], actor=request.user,
            )
            messages.success(request, "Your complaint has been submitted.")
            return redirect("cases:detail", pk=case.pk)
        return render(request, "cases/case_form.html", {"form": form})


def get_viewable_case(user, pk):
    try:
        case = BASE_QS.get(pk=pk)
    except Case.DoesNotExist:
        raise Http404
    if not perms.can_view(user, case):
        raise Http404  # do not reveal that the case exists
    return case


class CaseDetailView(LoginRequiredMixin, View):
    def get(self, request, pk):
        case = get_viewable_case(request.user, pk)
        u = request.user
        ctx = {
            "case": case,
            "events": case.events.select_related("actor"),
            "route_form": RouteForm() if perms.can_route(u, case) else None,
            "assign_form": AssignForm(case=case) if perms.can_assign(u, case) else None,
            "status_form": StatusForm(case=case) if perms.can_change_status(u, case) else None,
        }
        return render(request, "cases/case_detail.html", ctx)


class CaseActionView(LoginRequiredMixin, View):
    """POST-only base: permission check, validate form, call service."""
    form_class = None

    def check(self, user, case):
        raise NotImplementedError

    def form_kwargs(self, case):
        return {}

    def run(self, case, form, user):
        raise NotImplementedError

    def post(self, request, pk):
        case = get_viewable_case(request.user, pk)
        if not self.check(request.user, case):
            raise PermissionDenied
        form = self.form_class(request.POST, **self.form_kwargs(case))
        if form.is_valid():
            try:
                self.run(case, form, request.user)
                messages.success(request, "Case updated.")
            except ValidationError as e:
                messages.error(request, " ".join(e.messages))
        else:
            messages.error(request, "Invalid input.")
        return redirect("cases:detail", pk=case.pk)


class CaseRouteView(CaseActionView):
    form_class = RouteForm
    check = staticmethod(perms.can_route)

    def run(self, case, form, user):
        services.route_case(case, form.cleaned_data["department"], user,
                            form.cleaned_data["note"])


class CaseAssignView(CaseActionView):
    form_class = AssignForm
    check = staticmethod(perms.can_assign)

    def form_kwargs(self, case):
        return {"case": case}

    def run(self, case, form, user):
        services.assign_case(case, form.cleaned_data["assignee"], user,
                             form.cleaned_data["note"])


class CaseStatusView(CaseActionView):
    form_class = StatusForm
    check = staticmethod(perms.can_change_status)

    def form_kwargs(self, case):
        return {"case": case}

    def run(self, case, form, user):
        services.change_status(case, form.cleaned_data["status"], user,
                               form.cleaned_data["note"])
