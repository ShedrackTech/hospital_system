"""All attendance changes go through here (transactions, rules, audit log)."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from core import audit

from . import permissions as perms
from .models import AttendanceCorrection, AttendanceRecord


def _open_today(user):
    return AttendanceRecord.objects.filter(
        user=user, clock_out__isnull=True, work_date=timezone.localdate()
    ).order_by("-clock_in").first()


def clock_in(user, request=None):
    if not perms.has_staff_profile(user):
        raise ValidationError("Only staff with a staff profile can clock in.")
    with transaction.atomic():
        if _open_today(user):
            raise ValidationError("You are already clocked in. Clock out first.")
        now = timezone.now()
        record = AttendanceRecord.objects.create(
            user=user, work_date=timezone.localdate(), clock_in=now,
            source=AttendanceRecord.Source.SELF, recorded_by=user,
        )
        audit.log(user, "attendance_clock_in", record, request=request)
    return record


def clock_out(user, request=None):
    with transaction.atomic():
        record = _open_today(user)
        if record is None:
            raise ValidationError(
                "You have no open clock-in for today. If you forgot to clock out "
                "earlier, ask your department head or an attendance officer to close it."
            )
        record.clock_out = timezone.now()
        record.save(update_fields=["clock_out"])
        audit.log(user, "attendance_clock_out", record, request=request)
    return record


def record_arrival(actor, target, request=None):
    """An attendance officer records someone who arrived. Confirmed straight away."""
    if not perms.can_record_arrival(actor):
        raise PermissionDenied
    if target.pk == actor.pk:
        raise ValidationError("You cannot record your own attendance. Clock in yourself.")
    if not target.is_active or not perms.has_staff_profile(target):
        raise ValidationError("That is not an active staff member with a staff profile.")
    with transaction.atomic():
        if _open_today(target):
            raise ValidationError(f"{target} is already clocked in.")
        now = timezone.now()
        record = AttendanceRecord.objects.create(
            user=target, work_date=timezone.localdate(), clock_in=now,
            source=AttendanceRecord.Source.OFFICER, recorded_by=actor,
            confirmed_by=actor, confirmed_at=now,
        )
        audit.log(actor, "attendance_recorded", record,
                  detail=f"Arrival of {target}", request=request)
    return record


def record_departure(actor, record, request=None):
    if not perms.can_manage_record(actor, record):
        raise PermissionDenied
    with transaction.atomic():
        record = AttendanceRecord.objects.select_for_update().get(pk=record.pk)
        if record.clock_out is not None:
            raise ValidationError("This record is already closed.")
        record.clock_out = timezone.now()
        record.save(update_fields=["clock_out"])
        audit.log(actor, "attendance_departure_recorded", record,
                  detail=f"Departure of {record.user}", request=request)
    return record


def confirm_record(actor, record, request=None):
    if not perms.can_manage_record(actor, record):
        raise PermissionDenied
    with transaction.atomic():
        record = AttendanceRecord.objects.select_for_update().get(pk=record.pk)
        if record.confirmed_at is not None:
            raise ValidationError("This record is already confirmed.")
        record.confirmed_by = actor
        record.confirmed_at = timezone.now()
        record.save(update_fields=["confirmed_by", "confirmed_at"])
        audit.log(actor, "attendance_confirmed", record,
                  detail=f"Record of {record.user}", request=request)
    return record


def correct_record(actor, record, new_in, new_out, reason, request=None):
    """Change the times. The old values and the reason are kept forever."""
    if not perms.can_manage_record(actor, record):
        raise PermissionDenied
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("A reason is required for every correction.")
    if new_in > timezone.now() + timedelta(minutes=1):
        raise ValidationError("The clock-in time cannot be in the future.")
    if new_out is not None and new_out <= new_in:
        raise ValidationError("The clock-out time must be after the clock-in time.")
    with transaction.atomic():
        record = AttendanceRecord.objects.select_for_update().get(pk=record.pk)
        AttendanceCorrection.objects.create(
            record=record, corrected_by=actor, reason=reason[:300],
            old_clock_in=record.clock_in, old_clock_out=record.clock_out,
            new_clock_in=new_in, new_clock_out=new_out,
        )
        record.clock_in = new_in
        record.clock_out = new_out
        record.work_date = timezone.localtime(new_in).date()
        record.confirmed_by = actor
        record.confirmed_at = timezone.now()
        record.save()
        audit.log(actor, "attendance_corrected", record,
                  detail=f"{record.user}: {reason[:200]}", request=request)
    return record


def find_staff_by_id(staff_id):
    User = get_user_model()
    staff_id = (staff_id or "").strip()
    return User.objects.filter(login_id__iexact=staff_id, is_active=True).exclude(
        role=User.Role.PATIENT
    ).first()


def panel_for(user):
    """Data for the attendance panel on a staff dashboard."""
    can_review = perms.sees_team(user)
    review_count = 0
    if can_review:
        review_count = perms.flagged(perms.visible_records(user)).exclude(user=user).count()
    return {
        "open": _open_today(user),
        "can_review": can_review,
        "review_count": review_count,
    }
