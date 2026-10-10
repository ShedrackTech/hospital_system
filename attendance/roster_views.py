from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, ListView, UpdateView

from core import audit
from core.mixins import AdminRequiredMixin

from . import roster_permissions as roster_perms
from . import roster_services as services
from .models import RosterEntry, ShiftType
from .roster_forms import AssignShiftForm, ShiftTypeForm
from .views import StaffOnlyMixin


class MyRosterView(StaffOnlyMixin, View):
    """A staff member's own planned shifts for the next four weeks."""

    def get(self, request):
        today = timezone.localdate()
        entries = RosterEntry.objects.filter(
            user=request.user, date__gte=today, date__lte=today + timedelta(days=28)
        ).select_related("shift", "building")
        return render(request, "attendance/roster_mine.html", {"entries": entries, "today": today})


class ManagerMixin(LoginRequiredMixin):
    """Admins, department heads and supervisors only."""

    def dispatch(self, request, *args, **kwargs):
        user = request.user
        if user.is_authenticated and not roster_perms.can_open_manager(user):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


def _monday(day):
    return day - timedelta(days=day.weekday())


class RosterManageView(ManagerMixin, View):
    """A week grid: staff down the side, days across the top."""

    def get(self, request):
        try:
            start = _monday(date.fromisoformat(request.GET.get("start", "")))
        except ValueError:
            start = _monday(timezone.localdate())
        days = [start + timedelta(days=i) for i in range(7)]

        staff = list(roster_perms.visible_staff(request.user).select_related(
            "staff_profile__department").order_by("first_name", "username"))
        editable_ids = set(roster_perms.manageable_staff(request.user).values_list("pk", flat=True))
        entries = RosterEntry.objects.filter(
            user__in=staff, date__gte=days[0], date__lte=days[-1]
        ).select_related("shift", "building")
        cells = {}
        for entry in entries:
            cells.setdefault((entry.user_id, entry.date), []).append(entry)

        rows = [{
            "user": person,
            "editable": person.pk in editable_ids,
            "cells": [cells.get((person.pk, day), []) for day in days],
        } for person in staff]

        return render(request, "attendance/roster_manage.html", {
            "days": days, "rows": rows, "today": timezone.localdate(),
            "prev_start": start - timedelta(days=7), "next_start": start + timedelta(days=7),
            "form": AssignShiftForm(actor=request.user),
            "can_edit_shifts": request.user.role in ("main_admin", "sub_admin"),
        })


class RosterAssignView(ManagerMixin, View):
    http_method_names = ["post"]

    def post(self, request):
        form = AssignShiftForm(request.POST, actor=request.user)
        start = request.POST.get("date_from", "")
        if form.is_valid():
            data = form.cleaned_data
            try:
                added = services.assign_shift(
                    request.user, data["staff"], data["shift"], data["date_from"],
                    data["date_to"], data["building"], data["note"], request=request,
                )
                messages.success(request, f"{added} shift(s) added to the roster.")
                start = data["date_from"].isoformat()
            except ValidationError as error:
                messages.error(request, " ".join(error.messages))
        else:
            problems = "; ".join(f"{field}: {' '.join(errors)}" for field, errors in form.errors.items())
            messages.error(request, f"Please check the form. {problems}")
        return redirect(f"{reverse('attendance:roster')}?start={start}")


class RosterRemoveView(ManagerMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        entry = get_object_or_404(
            RosterEntry.objects.select_related("user", "shift"),
            pk=pk, user__in=roster_perms.manageable_staff(request.user),
        )
        try:
            services.remove_entry(request.user, entry, request=request)
            messages.success(request, "Shift removed.")
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        return redirect(f"{reverse('attendance:roster')}?start={entry.date.isoformat()}")


# ---- Shift definitions (admins only) ----

class ShiftFormMixin:
    template_name = "attendance/shift_form.html"
    form_class = ShiftTypeForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = self.page_title
        return context

    def get_success_url(self):
        return reverse("attendance:shifts")


class ShiftTypeListView(AdminRequiredMixin, ListView):
    template_name = "attendance/shift_list.html"
    context_object_name = "shifts"
    queryset = ShiftType.objects.all()


class ShiftTypeCreateView(AdminRequiredMixin, ShiftFormMixin, CreateView):
    page_title = "New shift"

    def form_valid(self, form):
        response = super().form_valid(form)
        audit.log(self.request.user, "shift_created", self.object, request=self.request)
        messages.success(self.request, "Shift added.")
        return response


class ShiftTypeUpdateView(AdminRequiredMixin, ShiftFormMixin, UpdateView):
    queryset = ShiftType.objects.all()

    @property
    def page_title(self):
        return f"Edit {self.object.name}"

    def form_valid(self, form):
        response = super().form_valid(form)
        audit.log(self.request.user, "shift_updated", self.object, request=self.request)
        messages.success(self.request, "Shift updated.")
        return response
