"""
Staff management inside the hospital portal (replaces day-to-day use of Django admin).
Admin roles only. Staff are deactivated, never deleted, so cases, admissions and
audit entries keep their history. Every action is written to the audit log.
"""
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import DetailView, FormView, ListView

from cases.models import Case
from core import audit
from core.mixins import ADMIN_ROLES, AdminRequiredMixin
from departments.models import Department

from .models import User
from .staff_forms import (
    StaffCreateForm,
    StaffEditForm,
    StaffFilterForm,
    StaffPasswordForm,
)
from .staff_rules import can_manage

STAFF = User.objects.exclude(role=User.Role.PATIENT)


class StaffListView(AdminRequiredMixin, ListView):
    template_name = "accounts/staff_list.html"
    context_object_name = "members"  # not "user": that would hide the logged-in user
    paginate_by = 20

    def get_queryset(self):
        self.form = StaffFilterForm(self.request.GET)
        members = STAFF.select_related("supervisor", "staff_profile__department")
        if self.form.is_valid():
            data = self.form.cleaned_data
            q = (data.get("q") or "").strip()
            if q:
                members = members.filter(
                    Q(first_name__icontains=q) | Q(last_name__icontains=q)
                    | Q(login_id__icontains=q) | Q(username__icontains=q)
                    | Q(phone__icontains=q)
                )
            if data.get("role"):
                members = members.filter(role=data["role"])
            if data.get("department"):
                members = members.filter(staff_profile__department=data["department"])
            if data.get("status") == "active":
                members = members.filter(is_active=True)
            elif data.get("status") == "inactive":
                members = members.filter(is_active=False)
        return members.order_by("login_id")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        members = list(context["members"])
        for member in members:
            member.manageable = can_manage(self.request.user, member)
        context["members"] = members
        context["form"] = self.form
        params = self.request.GET.copy()
        params.pop("page", None)
        context["query_string"] = params.urlencode()
        return context


class StaffDetailView(AdminRequiredMixin, DetailView):
    """Account and job details only. No medical information."""

    template_name = "accounts/staff_detail.html"
    context_object_name = "member"

    def get_queryset(self):
        return STAFF.select_related("supervisor", "staff_profile__department")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        member = self.object
        context["profile"] = getattr(member, "staff_profile", None)
        context["headed"] = getattr(member, "headed_department", None)
        context["team"] = member.team.filter(is_active=True)
        context["manageable"] = can_manage(self.request.user, member)
        return context


class FormPageMixin:
    template_name = "accounts/staff_form.html"
    page_title = ""
    submit_label = "Save"

    def get_cancel_url(self):
        return reverse("accounts:staff_list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_title=self.page_title, submit_label=self.submit_label,
                       cancel_url=self.get_cancel_url())
        return context


class StaffCreateView(AdminRequiredMixin, FormPageMixin, FormView):
    form_class = StaffCreateForm
    page_title = "Add staff"
    submit_label = "Create account"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["actor"] = self.request.user
        return kwargs

    def form_valid(self, form):
        user = form.save()
        audit.log(self.request.user, "staff_created", user,
                  detail=f"Role {user.get_role_display()}", request=self.request)
        messages.success(
            self.request,
            f"Account created. Staff ID: {user.login_id}. Give them the temporary password.",
        )
        return redirect("accounts:staff_detail", pk=user.pk)


class ManagedUserMixin(AdminRequiredMixin):
    """Loads the staff member from the URL and checks the actor may manage them."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if request.user.role not in ADMIN_ROLES:
            raise PermissionDenied
        self.target = get_object_or_404(STAFF, pk=kwargs["pk"])
        if not can_manage(request.user, self.target):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_cancel_url(self):
        return reverse("accounts:staff_detail", args=[self.target.pk])


class StaffUpdateView(ManagedUserMixin, FormPageMixin, FormView):
    form_class = StaffEditForm
    submit_label = "Save changes"

    @property
    def page_title(self):
        return f"Edit {self.target.get_full_name() or self.target.username}"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs.update(actor=self.request.user, target=self.target)
        return kwargs

    def form_valid(self, form):
        changed = form.save()
        audit.log(self.request.user, "staff_updated", self.target,
                  detail="Changed: " + (", ".join(changed) or "nothing"),
                  request=self.request)
        messages.success(self.request, "Staff details updated.")
        return redirect("accounts:staff_detail", pk=self.target.pk)


class StaffPasswordView(ManagedUserMixin, FormPageMixin, FormView):
    form_class = StaffPasswordForm
    submit_label = "Set password"

    @property
    def page_title(self):
        return f"Reset password for {self.target.get_full_name() or self.target.username}"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["target"] = self.target
        return kwargs

    def form_valid(self, form):
        self.target.set_password(form.cleaned_data["password1"])
        self.target.save(update_fields=["password"])
        # The password itself is never logged
        audit.log(self.request.user, "staff_password_reset", self.target,
                  detail="Password reset by an administrator", request=self.request)
        messages.success(self.request, "Password changed. Give the new temporary password to the staff member.")
        return redirect("accounts:staff_detail", pk=self.target.pk)


class StaffActiveView(ManagedUserMixin, View):
    """Confirm page (GET) and action (POST) to deactivate or reactivate an account."""

    activate = False

    def get(self, request, pk):
        warnings = []
        if not self.activate:
            headed = getattr(self.target, "headed_department", None)
            if headed:
                warnings.append(f"They head the {headed.name} department. They will be removed as head.")
            cases = Case.objects.filter(
                assigned_to=self.target, status__in=["assigned", "in_treatment"]
            ).count()
            if cases:
                warnings.append(f"They have {cases} active case(s). Ask the department head to reassign them.")
            reports = self.target.team.filter(is_active=True).count()
            if reports:
                warnings.append(f"{reports} active staff member(s) report to them.")
        return render(request, "accounts/staff_confirm.html", {
            "member": self.target, "activate": self.activate, "warnings": warnings,
        })

    def post(self, request, pk):
        with transaction.atomic():
            target = self.target
            target.is_active = self.activate
            target.save(update_fields=["is_active"])
            detail = "Account reactivated" if self.activate else "Account deactivated"
            if not self.activate:
                headed = getattr(target, "headed_department", None)
                if headed:
                    Department.objects.filter(pk=headed.pk).update(head=None)
                    detail += f"; removed as head of {headed.name}"
            audit.log(request.user,
                      "staff_reactivated" if self.activate else "staff_deactivated",
                      target, detail=detail, request=request)
        messages.success(request, detail + ".")
        return redirect("accounts:staff_detail", pk=target.pk)
