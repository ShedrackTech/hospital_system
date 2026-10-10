"""Roster changes and the roster-versus-attendance checks."""
from datetime import datetime, timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from core import audit

from . import roster_permissions as roster_perms
from .models import RosterEntry

GRACE_MINUTES = 15       # arriving later than this after the shift start counts as late
MAX_RANGE_DAYS = 31


def assign_shift(actor, users, shift, date_from, date_to, building=None, note="", request=None):
    """Plan `shift` for every user on every day from date_from to date_to. Returns how many were added."""
    users = list(users)
    if not users:
        raise ValidationError("Choose at least one staff member.")
    if not shift.is_active:
        raise ValidationError("That shift is no longer available.")
    if date_to < date_from:
        raise ValidationError("The end date must not be before the start date.")
    if date_from < timezone.localdate():
        raise ValidationError("The roster cannot be planned for days that have passed.")
    if (date_to - date_from).days + 1 > MAX_RANGE_DAYS:
        raise ValidationError(f"Plan at most {MAX_RANGE_DAYS} days at a time.")
    for user in users:
        if not roster_perms.can_manage_roster_for(actor, user):
            raise PermissionDenied

    created = 0
    with transaction.atomic():
        day = date_from
        while day <= date_to:
            for user in users:
                _, was_created = RosterEntry.objects.get_or_create(
                    user=user, date=day, shift=shift,
                    defaults={"building": building, "note": (note or "")[:200],
                              "created_by": actor},
                )
                created += was_created
            day += timedelta(days=1)
        audit.log(
            actor, "roster_assigned", shift,
            detail=f"{shift.name}: {len(users)} staff, {date_from} to {date_to}, {created} added",
            request=request,
        )
    return created


def remove_entry(actor, entry, request=None):
    if not roster_perms.can_manage_roster_for(actor, entry.user):
        raise PermissionDenied
    if entry.date < timezone.localdate():
        raise ValidationError("Past shifts cannot be removed.")
    with transaction.atomic():
        detail = f"{entry.user} {entry.date} {entry.shift.name}"
        entry.delete()
        audit.log(actor, "roster_removed", None, detail=detail, request=request)


# ---- roster compared with attendance ----

def shift_start(date, shift):
    return timezone.make_aware(datetime.combine(date, shift.start_time))


def schedule_map(records):
    """{(user_id, date): [RosterEntry, ...]} for the given attendance records."""
    records = list(records)
    if not records:
        return {}
    entries = RosterEntry.objects.filter(
        user_id__in={r.user_id for r in records}, date__in={r.work_date for r in records}
    ).select_related("shift", "building")
    result = {}
    for entry in entries:
        result.setdefault((entry.user_id, entry.date), []).append(entry)
    return result


def evaluate(record, entries):
    """Returns (label, minutes_late). The planned shift closest to the clock-in is used."""
    if not entries:
        return "", 0
    entry = min(entries, key=lambda e: abs(
        (record.clock_in - shift_start(record.work_date, e.shift)).total_seconds()))
    start = shift_start(record.work_date, entry.shift)
    late = int((record.clock_in - start).total_seconds() // 60) - GRACE_MINUTES
    return f"{entry.shift.name} {entry.shift.start_time:%H:%M}-{entry.shift.end_time:%H:%M}", max(late, 0)


def missing_today(actor):
    """Planned for a shift that has started (plus grace) but no attendance record today."""
    from .models import AttendanceRecord

    today = timezone.localdate()
    now = timezone.now()
    team = roster_perms.visible_staff(actor).exclude(pk=actor.pk)
    clocked = set(AttendanceRecord.objects.filter(work_date=today).values_list("user_id", flat=True))
    missing = []
    entries = RosterEntry.objects.filter(date=today, user__in=team).select_related(
        "shift", "user__staff_profile__department")
    for entry in entries:
        started = shift_start(today, entry.shift) + timedelta(minutes=GRACE_MINUTES)
        if started < now and entry.user_id not in clocked:
            missing.append(entry)
    return missing
