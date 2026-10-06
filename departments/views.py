from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import Count, Q
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from core.mixins import ADMIN_ROLES, AdminRequiredMixin, StaffRequiredMixin

from .forms import DepartmentForm, StaffProfileForm
from .models import Department, StaffProfile


def visible_departments(user):
    """
    Main Admin and Sub Admin see every department.
    Everyone else sees only the department they head or belong to.
    """
    if user.role in ADMIN_ROLES:
        return Department.objects.all()
    own = Department.objects.filter(Q(head=user) | Q(staff__user=user))
    return Department.objects.filter(pk__in=own.values("pk"))


class DepartmentListView(StaffRequiredMixin, ListView):
    template_name = "departments/department_list.html"
    context_object_name = "departments"

    def get_queryset(self):
        return (
            visible_departments(self.request.user)
            .select_related("head")
            .annotate(staff_count=Count("staff"))
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["can_manage"] = self.request.user.role in ADMIN_ROLES
        return context


class DepartmentDetailView(StaffRequiredMixin, DetailView):
    template_name = "departments/department_detail.html"
    context_object_name = "department"

    def get_queryset(self):
        # A department the user can't see returns 404
        return visible_departments(self.request.user).select_related("head")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["staff_profiles"] = self.object.staff.select_related("user")
        context["can_manage"] = self.request.user.role in ADMIN_ROLES
        return context


class DepartmentCreateView(AdminRequiredMixin, SuccessMessageMixin, CreateView):
    model = Department
    form_class = DepartmentForm
    template_name = "departments/department_form.html"
    success_url = reverse_lazy("departments:list")
    success_message = "Department created."


class DepartmentUpdateView(AdminRequiredMixin, SuccessMessageMixin, UpdateView):
    model = Department
    form_class = DepartmentForm
    template_name = "departments/department_form.html"
    success_url = reverse_lazy("departments:list")
    success_message = "Department updated."


class StaffProfileCreateView(AdminRequiredMixin, SuccessMessageMixin, CreateView):
    model = StaffProfile
    form_class = StaffProfileForm
    template_name = "departments/staff_form.html"
    success_message = "Staff profile created."

    def get_success_url(self):
        if self.object.department_id:
            return reverse("departments:detail", args=[self.object.department_id])
        return reverse("departments:list")


class StaffProfileUpdateView(AdminRequiredMixin, SuccessMessageMixin, UpdateView):
    model = StaffProfile
    form_class = StaffProfileForm
    template_name = "departments/staff_form.html"
    success_message = "Staff profile updated."

    def get_success_url(self):
        if self.object.department_id:
            return reverse("departments:detail", args=[self.object.department_id])
        return reverse("departments:list")
