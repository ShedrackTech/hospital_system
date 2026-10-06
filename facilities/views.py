from django.contrib import messages
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import Count, F, Prefetch, Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views.generic import (
    CreateView,
    DetailView,
    FormView,
    ListView,
    UpdateView,
)

from core.mixins import AdminRequiredMixin

from .forms import BuildingForm, BulkBedForm, WardForm
from .models import Building, Ward


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
