"""All appointment state changes go through here.

Each function runs in a transaction with row locks, writes the audit log in the
same transaction (if the audit write fails, the action fails), and raises
django ValidationError when a rule is broken. The reason for a visit and the
reason for a cancellation are never copied into the audit log.
"""
from collections import namedtuple
from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from core import audit
from patients.models import Patient

from . import permissions, rules
from .models import Appointment, DoctorAvailability

User = get_user_model()

Slot = namedtuple("Slot", "start end")


def _audit(actor, action, obj, patient=None, detail="", request=None):
    # One place to adjust if the audit helper's signature ever changes.
    audit.log(actor, action, obj, patient=patient, detail=detail, request=request)


def _name(user):
    return user.get_full_name() or user.get_username()


def _at(day, t):
    return timezone.make_aware(datetime.combine(day, t))


# ---------- free times ----------

def available_slots(doctor, day, now=None):
    """Free, bookable slots for one doctor on one local date (a list of Slot)."""
    now = now or timezone.now()
    today = timezone.localdate(now)
    if day < today or day > today + timedelta(days=rules.MAX_DAYS_AHEAD):
        return []
    if not permissions.is_eligible_doctor(doctor):
        return []
    windows = list(
        DoctorAvailability.objects.filter(doctor=doctor, weekday=day.weekday()).order_by("start_time")
    )
    if not windows:
        return []

    day_start = _at(day, time.min)
    day_end = day_start + timedelta(days=1)
    booked = list(
        Appointment.objects.filter(
            doctor=doctor,
            status=Appointment.Status.SCHEDULED,
            starts_at__lt=day_end,
            ends_at__gt=day_start,
        ).values_list("starts_at", "ends_at")
    )

    slots = []
    for w in windows:
        step = timedelta(minutes=w.slot_minutes)
        cursor = _at(day, w.start_time)
        end = _at(day, w.end_time)
        while cursor + step <= end:
            taken = any(b_start < cursor + step and b_end > cursor for b_start, b_end in booked)
            if cursor > now and not taken:
                slots.append(Slot(cursor, cursor + step))
            cursor += step
    return slots


# ---------- booking ----------

def book_appointment(patient, doctor, starts_at, reason, actor, request=None):
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("Please say briefly why the visit is needed.")
    if len(reason) > rules.REASON_MAX_LENGTH:
        raise ValidationError(f"Please keep the reason under {rules.REASON_MAX_LENGTH} characters.")
    if not permissions.can_book_for(actor, patient):
        raise PermissionDenied("You may not book for this patient.")
    if timezone.is_naive(starts_at):
        starts_at = timezone.make_aware(starts_at)

    with transaction.atomic():
        # Lock order is always patient, then doctor, so two requests cannot deadlock.
        patient = Patient.objects.select_for_update().get(pk=patient.pk)
        doctor = User.objects.select_for_update().get(pk=doctor.pk)
        if not patient.user.is_active:
            raise ValidationError("This patient account is not active.")

        now = timezone.now()
        slot = next(
            (s for s in available_slots(doctor, timezone.localdate(starts_at), now) if s.start == starts_at),
            None,
        )
        if slot is None:
            raise ValidationError("That time is not available. Please choose another time.")

        Status = Appointment.Status
        upcoming = Appointment.objects.filter(patient=patient, status=Status.SCHEDULED, ends_at__gt=now).count()
        if upcoming >= rules.MAX_UPCOMING_PER_PATIENT:
            raise ValidationError(
                f"A patient can have at most {rules.MAX_UPCOMING_PER_PATIENT} upcoming appointments. "
                "Cancel one or wait until one has taken place."
            )
        if Appointment.objects.filter(
            patient=patient, status=Status.SCHEDULED, starts_at__lt=slot.end, ends_at__gt=slot.start
        ).exists():
            raise ValidationError("This patient already has an appointment at that time.")

        try:
            with transaction.atomic():
                appt = Appointment.objects.create(
                    patient=patient,
                    doctor=doctor,
                    department=doctor.staff_profile.department,
                    starts_at=slot.start,
                    ends_at=slot.end,
                    reason=reason,
                    booked_by=actor,
                )
        except IntegrityError:
            raise ValidationError("That time was just taken. Please choose another time.")

        _audit(
            actor,
            "appointment_booked",
            appt,
            patient=patient,
            detail=f"With {_name(doctor)} on {timezone.localtime(slot.start):%d %b %Y %H:%M}",
            request=request,
        )
    return appt


# ---------- cancelling and closing ----------

def cancel_appointment(appt, actor, reason="", request=None):
    reason = (reason or "").strip()
    with transaction.atomic():
        appt = Appointment.objects.select_for_update().get(pk=appt.pk)
        problem = permissions.cancel_problem(actor, appt)
        if problem:
            raise ValidationError(problem)
        by_patient = permissions.is_own_patient(actor, appt)
        if not by_patient and not reason:
            raise ValidationError("Please give a reason for cancelling this appointment.")

        appt.status = Appointment.Status.CANCELLED
        appt.cancel_reason = reason
        appt.closed_by = actor
        appt.closed_at = timezone.now()
        appt.save(update_fields=["status", "cancel_reason", "closed_by", "closed_at", "updated_at"])
        _audit(
            actor,
            "appointment_cancelled",
            appt,
            patient=appt.patient,
            detail="Cancelled by the patient" if by_patient else "Cancelled by staff",
            request=request,
        )
    return appt


def close_appointment(appt, new_status, actor, request=None):
    action = {
        Appointment.Status.COMPLETED: "appointment_completed",
        Appointment.Status.NO_SHOW: "appointment_no_show",
    }.get(new_status)
    if action is None:
        raise ValidationError("An appointment can only be marked completed or no-show.")
    with transaction.atomic():
        appt = Appointment.objects.select_for_update().get(pk=appt.pk)
        problem = permissions.close_problem(actor, appt)
        if problem:
            raise ValidationError(problem)
        appt.status = new_status
        appt.closed_by = actor
        appt.closed_at = timezone.now()
        appt.save(update_fields=["status", "closed_by", "closed_at", "updated_at"])
        _audit(actor, action, appt, patient=appt.patient, request=request)
    return appt


# ---------- availability ----------

def _minutes(t):
    return t.hour * 60 + t.minute


def add_availability(actor, doctor, weekday, start_time, end_time, slot_minutes, request=None):
    if not permissions.can_manage_availability(actor, doctor):
        raise PermissionDenied("You may not change this doctor's availability.")
    if slot_minutes not in rules.SLOT_MINUTES_CHOICES:
        raise ValidationError("Choose a valid slot length.")
    if end_time <= start_time:
        raise ValidationError("The end time must be after the start time.")
    length = _minutes(end_time) - _minutes(start_time)
    if length % slot_minutes != 0:
        raise ValidationError(
            f"The window is {length} minutes long, which does not divide evenly into {slot_minutes} minute slots."
        )

    with transaction.atomic():
        User.objects.select_for_update().get(pk=doctor.pk)
        clash = DoctorAvailability.objects.filter(
            doctor=doctor, weekday=weekday, start_time__lt=end_time, end_time__gt=start_time
        ).exists()
        if clash:
            raise ValidationError("This overlaps another window on the same day.")
        window = DoctorAvailability.objects.create(
            doctor=doctor,
            weekday=weekday,
            start_time=start_time,
            end_time=end_time,
            slot_minutes=slot_minutes,
            created_by=actor,
        )
        _audit(actor, "availability_added", window, detail=f"For {_name(doctor)}", request=request)
    return window


def remove_availability(actor, window, request=None):
    """Removing a window never touches appointments already booked."""
    if not permissions.can_manage_availability(actor, window.doctor):
        raise PermissionDenied("You may not change this doctor's availability.")
    with transaction.atomic():
        _audit(actor, "availability_removed", window, detail=f"For {_name(window.doctor)}", request=request)
        window.delete()
