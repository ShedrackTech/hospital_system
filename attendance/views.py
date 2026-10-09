from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View
from django.views.generic import ListView

from . import permissions as perms
from . import services
from .forms import CorrectionForm, FilterForm, StaffIdForm
from .models import AttendanceRecord


class StaffOnlyMixin(LoginRequiredMixin):
    """Staff with a staff profile only (patients and profile-less accounts get a 403)."""

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not perms.has_staff_profile(request.user):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class TeamAccessMixin(LoginRequiredMixin):
    """Admins, attendance officers, department heads and supervisors (not patients)."""

    def dispatch(self, request, *args, **kwargs):
        user = request.user
        if user.is_authenticated and (user.is_patient or not perms.sees_team(user)):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


def _back(request):
    return redirect("accounts:dashboard" if request.POST.get("next") == "dashboard"
                    else "attendance:mine")


class MyAttendanceView(StaffOnlyMixin, View):
    def get(self, request):
        records = AttendanceRecord.objects.filter(user=request.user).select_related(
            "confirmed_by", "recorded_by"
        ).annotate(correction_count=Count("corrections"))[:60]
        return render(request, "attendance/mine.html", {
            "records": records,
            "panel": services.panel_for(request.user),
        })


class ClockInView(StaffOnlyMixin, View):
    http_method_names = ["post"]

    def post(self, request):
        try:
            services.clock_in(request.user, request=request)
            messages.success(request, "You are clocked in.")
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        return _back(request)


class ClockOutView(StaffOnlyMixin, View):
    http_method_names = ["post"]

    def post(self, request):
        try:
            services.clock_out(request.user, request=request)
            messages.success(request, "You are clocked out.")
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        return _back(request)


class TeamAttendanceView(TeamAccessMixin, ListView):
    """Heads, supervisors, attendance officers and admins. Each sees only their own scope."""

    template_name = "attendance/team.html"
    context_object_name = "records"
    paginate_by = 30

    def get_queryset(self):
        self.form = FilterForm(self.request.GET)
        records = perms.visible_records(self.request.user)
        data = self.form.cleaned_data if self.form.is_valid() else {}
        status = data.get("status", "")
        day = data.get("date")
        if status == "flagged":
            records = perms.flagged(records)
        else:
            records = records.filter(work_date=day or timezone.localdate())
            if status == "unconfirmed":
                records = records.filter(confirmed_at__isnull=True)
            elif status == "open":
                records = records.filter(clock_out__isnull=True)
        query = (data.get("q") or "").strip()
        if query:
            records = records.filter(
                Q(user__first_name__icontains=query) | Q(user__last_name__icontains=query)
                | Q(user__login_id__icontains=query)
            )
        return records.annotate(correction_count=Count("corrections")).order_by("-clock_in")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        today = timezone.localdate()
        records = list(context["records"])
        for record in records:
            record.manageable = perms.can_manage_record(user, record)
            record.is_flagged = record.work_date < today and (
                record.confirmed_at is None or record.clock_out is None)
        context["records"] = records
        context["form"] = self.form
        context["arrival_form"] = StaffIdForm() if perms.can_record_arrival(user) else None
        params = self.request.GET.copy()
        params.pop("page", None)
        context["query_string"] = params.urlencode()
        return context


class RecordActionView(TeamAccessMixin, View):
    """POST-only base: load a record the user may see, check they may manage it, act."""

    http_method_names = ["post"]
    success_text = "Done."

    def run(self, request, record):
        raise NotImplementedError

    def post(self, request, pk):
        record = get_object_or_404(perms.visible_records(request.user), pk=pk)
        if not perms.can_manage_record(request.user, record):
            raise PermissionDenied
        try:
            self.run(request, record)
            messages.success(request, self.success_text)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        return redirect("attendance:team")


class ConfirmView(RecordActionView):
    success_text = "Record confirmed."

    def run(self, request, record):
        services.confirm_record(request.user, record, request=request)


class DepartureView(RecordActionView):
    success_text = "Departure recorded."

    def run(self, request, record):
        services.record_departure(request.user, record, request=request)


class OfficerRecordView(TeamAccessMixin, View):
    http_method_names = ["post"]

    def post(self, request):
        if not perms.can_record_arrival(request.user):
            raise PermissionDenied
        form = StaffIdForm(request.POST)
        if form.is_valid():
            target = services.find_staff_by_id(form.cleaned_data["staff_id"])
            if target is None:
                messages.error(request, "No active staff member has that staff ID.")
            else:
                try:
                    services.record_arrival(request.user, target, request=request)
                    messages.success(request, f"Arrival recorded for {target}.")
                except ValidationError as error:
                    messages.error(request, " ".join(error.messages))
        else:
            messages.error(request, "Enter a staff ID.")
        return redirect("attendance:team")


class CorrectView(TeamAccessMixin, View):
    def _record(self, request, pk):
        record = get_object_or_404(perms.visible_records(request.user), pk=pk)
        if not perms.can_manage_record(request.user, record):
            raise PermissionDenied
        return record

    def get(self, request, pk):
        record = self._record(request, pk)
        return self._render(request, record, CorrectionForm(record=record))

    def post(self, request, pk):
        record = self._record(request, pk)
        form = CorrectionForm(request.POST, record=record)
        if form.is_valid():
            try:
                services.correct_record(
                    request.user, record, form.cleaned_data["clock_in"],
                    form.cleaned_data["clock_out"], form.cleaned_data["reason"],
                    request=request,
                )
                messages.success(request, "Record corrected. The old times are kept in its history.")
                return redirect("attendance:team")
            except ValidationError as error:
                form.add_error(None, error)
        return self._render(request, record, form)

    def _render(self, request, record, form):
        return render(request, "attendance/correct.html", {
            "record": record, "form": form,
            "corrections": record.corrections.select_related("corrected_by"),
        })
