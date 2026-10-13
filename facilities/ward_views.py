from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from core import audit

from . import ward_permissions as perms
from . import ward_services as services
from .ward_forms import AssignNursesForm
from .models import Admission, Ward, WardAssignment


class ManagerMixin(LoginRequiredMixin):
    """Admin roles and department heads only."""

    def dispatch(self, request, *args, **kwargs):
        user = request.user
        if user.is_authenticated and not perms.can_open_manager(user):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class WardStaffView(ManagerMixin, View):
    """Which nurses are assigned to which ward."""

    def get(self, request):
        editable = set(perms.manageable_nurses(request.user).values_list("pk", flat=True))
        wards = Ward.objects.select_related("building", "department").prefetch_related(
            Prefetch("assignments", queryset=WardAssignment.objects.select_related("user"))
        ).order_by("building__name", "name")
        rows = []
        for ward in wards:
            assignments = list(ward.assignments.all())
            for assignment in assignments:
                assignment.editable = assignment.user_id in editable
            rows.append({"ward": ward, "assignments": assignments})
        return render(request, "facilities/ward_staff.html", {
            "rows": rows, "form": AssignNursesForm(actor=request.user),
        })


class WardAssignView(ManagerMixin, View):
    http_method_names = ["post"]

    def post(self, request):
        form = AssignNursesForm(request.POST, actor=request.user)
        if form.is_valid():
            try:
                added = services.assign_nurses(
                    request.user, form.cleaned_data["nurses"], form.cleaned_data["ward"],
                    request=request,
                )
                messages.success(request, f"{added} nurse(s) assigned." if added
                                 else "They were already assigned to that ward.")
            except ValidationError as error:
                messages.error(request, " ".join(error.messages))
        else:
            messages.error(request, "Choose at least one nurse and a ward.")
        return redirect("facilities:ward_staff")


class WardAssignmentRemoveView(ManagerMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        assignment = get_object_or_404(
            WardAssignment.objects.select_related("user", "ward"),
            pk=pk, user__in=perms.manageable_nurses(request.user),
        )
        services.remove_assignment(request.user, assignment, request=request)
        messages.success(request, "Nurse removed from the ward.")
        return redirect("facilities:ward_staff")


class MyWardView(LoginRequiredMixin, View):
    """The patients currently admitted in the wards this nurse is assigned to."""

    def get(self, request):
        user = request.user
        if user.is_patient or getattr(user, "staff_profile", None) is None:
            raise PermissionDenied
        wards = []
        assignments = WardAssignment.objects.filter(user=user).select_related("ward__building")
        for assignment in assignments:
            ward = assignment.ward
            admissions = {
                a.bed_id: a for a in Admission.objects.filter(
                    bed__ward=ward, discharged_at__isnull=True
                ).select_related("case__patient__user", "case__assigned_to", "bed")
            }
            rows = [{"bed": bed, "admission": admissions.get(bed.pk)} for bed in ward.beds.all()]
            wards.append({"ward": ward, "rows": rows, "occupied": len(admissions), "total": len(rows)})
        if wards:  # seeing patient names and beds is an access to patient data
            audit.log(user, "ward_list_viewed", detail=", ".join(str(w["ward"]) for w in wards),
                      request=request)
        return render(request, "facilities/my_ward.html", {"wards": wards})
