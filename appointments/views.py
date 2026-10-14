from datetime import datetime, time, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core import audit
from core.mixins import is_front_desk
from patients.models import Patient

from . import permissions, rules, services
from .forms import AvailabilityForm, BookingForm, BookingLookupForm, CancelForm
from .models import Appointment, DoctorAvailability


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _find_patient(card):
    """Find an active patient by card number (PAT000001), which is the patient's login ID."""
    return (
        Patient.objects.select_related("user")
        .filter(user__login_id__iexact=card, user__is_active=True)
        .first()
    )


def _errors(request, exc):
    messages.error(request, " ".join(exc.messages))


@login_required
def home(request):
    if request.user.role == "patient":
        return redirect("appointments:mine")
    if permissions.can_open_staff_list(request.user):
        return redirect("appointments:staff_list")
    raise PermissionDenied


# ---------- patient ----------

@login_required
def mine(request):
    patient = permissions.patient_of(request.user)
    if patient is None:
        raise PermissionDenied
    now = timezone.now()
    qs = Appointment.objects.filter(patient=patient).select_related("doctor", "department")
    upcoming = qs.filter(status=Appointment.Status.SCHEDULED, ends_at__gt=now).order_by("starts_at")
    history = qs.exclude(pk__in=upcoming.values("pk")).order_by("-starts_at")[:50]
    return render(request, "appointments/mine.html", {"upcoming": upcoming, "history": history})


# ---------- booking (patient for self, front desk for a patient) ----------

@login_required
def book(request):
    user = request.user
    staff_booking = False
    patient_card = ""
    if user.role == "patient":
        patient = permissions.patient_of(user)
        if patient is None:
            raise PermissionDenied
    elif is_front_desk(user):
        staff_booking = True
        patient_card = (request.POST.get("patient") or request.GET.get("patient") or "").strip()
        patient = _find_patient(patient_card) if patient_card else None
        if patient_card and patient is None:
            messages.error(request, "No active patient found with that card number.")
    else:
        raise PermissionDenied

    lookup = None
    form = None
    doctor = day = None
    lookup_ok = False

    if request.method == "POST":
        lookup = BookingLookupForm(request.POST)
        if lookup.is_valid():
            doctor, day = lookup.cleaned_data["doctor"], lookup.cleaned_data["date"]
            slots = services.available_slots(doctor, day)
            lookup_ok = True
            form = BookingForm(request.POST, slots=slots)
            if patient is not None and form.is_valid():
                try:
                    appt = services.book_appointment(
                        patient, doctor, datetime.fromisoformat(form.cleaned_data["slot"]),
                        form.cleaned_data["reason"], user, request=request,
                    )
                except ValidationError as exc:
                    form.add_error(None, exc)
                else:
                    messages.success(request, "The appointment has been booked.")
                    return redirect("appointments:detail", pk=appt.pk)
    elif "doctor" in request.GET:
        lookup = BookingLookupForm(request.GET)
        if lookup.is_valid() and (patient is not None or not staff_booking):
            doctor, day = lookup.cleaned_data["doctor"], lookup.cleaned_data["date"]
            slots = services.available_slots(doctor, day)
            lookup_ok = True
            form = BookingForm(slots=slots) if slots else None
    else:
        lookup = BookingLookupForm()

    if staff_booking and patient is None:
        form = None
        lookup_ok = False

    return render(request, "appointments/book.html", {
        "lookup": lookup, "form": form, "doctor": doctor, "day": day, "lookup_ok": lookup_ok,
        "patient": patient, "patient_card": patient_card, "staff_booking": staff_booking,
        "max_days": rules.MAX_DAYS_AHEAD,
    })


# ---------- staff list ----------

@login_required
def staff_list(request):
    user = request.user
    if not permissions.can_open_staff_list(user):
        raise PermissionDenied

    today_start = timezone.make_aware(datetime.combine(timezone.localdate(), time.min))
    tomorrow_start = today_start + timedelta(days=1)
    qs = permissions.visible_appointments(user)

    when = request.GET.get("when", "upcoming")
    if when == "today":
        qs = qs.filter(starts_at__gte=today_start, starts_at__lt=tomorrow_start).order_by("starts_at")
    elif when == "past":
        qs = qs.filter(starts_at__lt=today_start).order_by("-starts_at")
    else:
        when = "upcoming"
        qs = qs.filter(starts_at__gte=today_start).order_by("starts_at")

    status = request.GET.get("status", "")
    if status in Appointment.Status.values:
        qs = qs.filter(status=status)
    else:
        status = ""

    rows = list(qs[:200])
    audit.log(user, "appointment_list_viewed", user, detail=f"Filter: {when} {status}".strip(), request=request)
    return render(request, "appointments/staff_list.html", {
        "rows": rows, "when": when, "status": status, "statuses": Appointment.Status.choices,
        "can_book": is_front_desk(user), "can_set_hours": permissions.can_open_availability(user),
        "truncated": len(rows) == 200,
    })


# ---------- one appointment ----------

def _get_visible(request, pk):
    appt = get_object_or_404(
        Appointment.objects.select_related("patient__user", "doctor", "department", "booked_by", "closed_by"), pk=pk
    )
    if not permissions.can_view(request.user, appt):
        raise Http404  # do not reveal that it exists
    return appt


@login_required
def detail(request, pk):
    appt = _get_visible(request, pk)
    user = request.user
    if not permissions.is_own_patient(user, appt):
        audit.log(user, "appointment_viewed", appt, patient=appt.patient, request=request)
    return render(request, "appointments/detail.html", {
        "appt": appt,
        "show_reason": permissions.can_see_reason(user, appt),
        "can_cancel": permissions.can_cancel(user, appt),
        "can_close": permissions.can_close(user, appt),
        "by_patient": permissions.is_own_patient(user, appt),
        "cancel_form": CancelForm(),
        "cancel_hours": rules.PATIENT_CANCEL_HOURS,
        "cancel_blocked": permissions.cancel_problem(user, appt),
    })


@login_required
@require_POST
def cancel(request, pk):
    appt = _get_visible(request, pk)
    form = CancelForm(request.POST)
    if form.is_valid():
        try:
            services.cancel_appointment(appt, request.user, form.cleaned_data["reason"], request=request)
        except ValidationError as exc:
            _errors(request, exc)
        else:
            messages.success(request, "The appointment has been cancelled.")
    else:
        messages.error(request, "The reason is too long.")
    return redirect("appointments:detail", pk=appt.pk)


@login_required
@require_POST
def close(request, pk):
    appt = _get_visible(request, pk)
    try:
        services.close_appointment(appt, request.POST.get("status", ""), request.user, request=request)
    except ValidationError as exc:
        _errors(request, exc)
    else:
        messages.success(request, "The outcome has been recorded.")
    return redirect("appointments:detail", pk=appt.pk)


# ---------- doctors' weekly availability ----------

@login_required
def availability(request):
    user = request.user
    if not permissions.can_open_availability(user):
        raise PermissionDenied
    doctors = permissions.manageable_doctors(user)
    wanted = _int_or_none(request.POST.get("doctor") or request.GET.get("doctor"))
    selected = (
        (doctors.filter(pk=wanted).first() if wanted else None)
        or doctors.filter(pk=user.pk).first()
        or doctors.first()
    )

    form = AvailabilityForm(request.POST or None)
    if request.method == "POST" and selected is not None and form.is_valid():
        cd = form.cleaned_data
        try:
            services.add_availability(
                user, selected, cd["weekday"], cd["start_time"], cd["end_time"], cd["slot_minutes"], request=request
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "The time window has been added.")
            return redirect(f"{request.path}?doctor={selected.pk}")

    windows = DoctorAvailability.objects.filter(doctor=selected) if selected else []
    return render(request, "appointments/availability.html", {
        "doctors": doctors, "selected": selected, "windows": windows, "form": form,
    })


@login_required
@require_POST
def availability_remove(request, pk):
    window = get_object_or_404(DoctorAvailability.objects.select_related("doctor"), pk=pk)
    if not permissions.can_manage_availability(request.user, window.doctor):
        raise Http404
    doctor_pk = window.doctor_id
    services.remove_availability(request.user, window, request=request)
    messages.success(request, "The time window has been removed. Existing appointments are not affected.")
    return redirect(f"{reverse('appointments:availability')}?doctor={doctor_pk}")
