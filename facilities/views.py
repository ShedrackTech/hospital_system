from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, F, Prefetch, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import (
    CreateView,
    DetailView,
    FormView,
    ListView,
    UpdateView,
)

from cases import permissions as case_perms
from cases.models import Case
from core.mixins import AdminRequiredMixin

from . import services
from .forms import AdmitForm, BuildingForm, BulkBedForm, WardForm
from .models import Admission, Building, Ward


class FormPageMixin:
    """Adds a page title and cancel link to the shared form template."""

    template_name = "facilities/form.html"
    page_title = ""
    cancel_url = reverse_lazy("facilities:overview")

    def get_page_title(self):
        return self.page_title

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = self.get_page_title()
        context["cancel_url"] = self.cancel_url
        return context


class FacilityOverviewView(AdminRequiredMixin, ListView):
    """Buildings, their wards, and bed occupancy."""

    template_name = "facilities/overview.html"
    context_object_name = "buildings"

    def get_queryset(self):
        wards = (
            Ward.objects.select_related("department")
            .annotate(
                total_beds=Count("beds"),
                occupied_beds=Count("beds", filter=Q(beds__is_occupied=True)),
            )
            .annotate(free_beds=F("total_beds") - F("occupied_beds"))
        )
        return Building.objects.prefetch_related(Prefetch("wards", queryset=wards))


class WardDetailView(AdminRequiredMixin, DetailView):
    template_name = "facilities/ward_detail.html"
    context_object_name = "ward"

    def get_queryset(self):
        return Ward.objects.select_related("building", "department")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        beds = list(self.object.beds.all())
        context["beds"] = beds
        context["total_beds"] = len(beds)
        context["occupied_beds"] = sum(1 for bed in beds if bed.is_occupied)
        context["free_beds"] = len(beds) - context["occupied_beds"]
        return context


class BuildingCreateView(
    AdminRequiredMixin, FormPageMixin, SuccessMessageMixin, CreateView
):
    form_class = BuildingForm
    page_title = "New building"
    success_url = reverse_lazy("facilities:overview")
    success_message = "Building created."


class BuildingUpdateView(
    AdminRequiredMixin, FormPageMixin, SuccessMessageMixin, UpdateView
):
    form_class = BuildingForm
    queryset = Building.objects.all()
    success_url = reverse_lazy("facilities:overview")
    success_message = "Building updated."

    def get_page_title(self):
        return f"Edit {self.object.name}"


class WardCreateView(AdminRequiredMixin, FormPageMixin, SuccessMessageMixin, CreateView):
    form_class = WardForm
    page_title = "New ward"
    success_message = "Ward created."

    def get_success_url(self):
        return reverse("facilities:ward_detail", args=[self.object.pk])


class WardUpdateView(AdminRequiredMixin, FormPageMixin, SuccessMessageMixin, UpdateView):
    form_class = WardForm
    queryset = Ward.objects.all()
    success_message = "Ward updated."

    def get_page_title(self):
        return f"Edit {self.object.name}"

    def get_success_url(self):
        return reverse("facilities:ward_detail", args=[self.object.pk])


class BedAddView(AdminRequiredMixin, FormPageMixin, FormView):
    form_class = BulkBedForm

    def dispatch(self, request, *args, **kwargs):
        # Resolve the ward first, so a bad ID returns 404
        self.ward = get_object_or_404(Ward, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_page_title(self):
        return f"Add beds to {self.ward.name}"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["cancel_url"] = reverse("facilities:ward_detail", args=[self.ward.pk])
        return context

    def form_valid(self, form):
        created, skipped = form.save(self.ward)
        message = f"{created} bed(s) added."
        if skipped:
            message += f" {skipped} already existed and were skipped."
        messages.success(self.request, message)
        return redirect("facilities:ward_detail", pk=self.ward.pk)


# ---- Admissions (assigned doctor or department head) ----


def _case_for_admission(user, case):
    """404 if the user cannot see the case, 403 if they cannot admit/discharge."""
    if not case_perms.can_view(user, case):
        raise Http404
    if not case_perms.can_admit(user, case):
        raise PermissionDenied


class AdmitView(LoginRequiredMixin, FormPageMixin, FormView):
    form_class = AdmitForm

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        self.case = get_object_or_404(
            Case.objects.select_related("patient", "department"), pk=kwargs["case_pk"]
        )
        _case_for_admission(request.user, self.case)
        return super().dispatch(request, *args, **kwargs)

    def get_page_title(self):
        return f"Admit case #{self.case.pk} to a bed"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["case"] = self.case
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["cancel_url"] = reverse("cases:detail", args=[self.case.pk])
        return context

    def form_valid(self, form):
        try:
            services.admit_patient(
                self.case, form.cleaned_data["bed"], self.request.user,
                form.cleaned_data["notes"],
            )
        except ValidationError as error:
            form.add_error(None, error)
            return self.form_invalid(form)
        messages.success(self.request, "Patient admitted.")
        return redirect("cases:detail", pk=self.case.pk)


class DischargeView(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        admission = get_object_or_404(
            Admission.objects.select_related("case__patient", "case__department"), pk=pk
        )
        _case_for_admission(request.user, admission.case)
        try:
            services.discharge_patient(admission, request.user)
            messages.success(request, "Patient discharged and bed freed.")
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        return redirect("cases:detail", pk=admission.case_id)


class AdmissionListView(AdminRequiredMixin, ListView):
    """For admins: who is in which bed (add ?show=all to include discharged)."""

    template_name = "facilities/admission_list.html"
    context_object_name = "admissions"
    paginate_by = 30

    def get_queryset(self):
        self.show_all = self.request.GET.get("show") == "all"
        admissions = Admission.objects.select_related(
            "case__patient__user", "case__department", "bed__ward__building"
        )
        if not self.show_all:
            admissions = admissions.filter(discharged_at__isnull=True)
        return admissions

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["show_all"] = self.show_all
        return context
