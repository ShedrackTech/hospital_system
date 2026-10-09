"""Who may clock in, see a team's attendance, confirm or correct records."""
from django.db.models import Q
from django.utils import timezone

from cases import permissions as case_perms

from .models import AttendanceRecord


def has_staff_profile(user):
    return bool(
        user.is_authenticated and not user.is_patient
        and getattr(user, "staff_profile", None) is not None
    )


def is_officer(user):
    """Attendance officer (e.g. gateman, HR): can record and confirm anyone's attendance."""
    profile = getattr(user, "staff_profile", None)
    return bool(profile and profile.attendance_officer)


def sees_team(user):
    return (
        case_perms.is_admin(user) or is_officer(user)
        or case_perms.headed_department(user) is not None or user.team.exists()
    )


def visible_records(user):
    """Records the user may see on the team page (their own are included)."""
    records = AttendanceRecord.objects.select_related(
        "user__staff_profile__department", "confirmed_by", "recorded_by"
    )
    if case_perms.is_admin(user) or is_officer(user):
        return records
    condition = Q(user__supervisor=user) | Q(user=user)
    dept = case_perms.headed_department(user)
    if dept:
        condition |= Q(user__staff_profile__department=dept)
    return records.filter(condition)


def flagged(records):
    """Earlier days that are still unconfirmed, or were never clocked out."""
    today = timezone.localdate()
    return records.filter(work_date__lt=today).filter(
        Q(confirmed_at__isnull=True) | Q(clock_out__isnull=True)
    )


def can_manage_record(actor, record):
    """Confirm, correct or close a record. Nobody manages their own record."""
    if record.user_id == actor.id:
        return False
    if case_perms.is_admin(actor) or is_officer(actor):
        return True
    if record.user.supervisor_id == actor.id:
        return True
    dept = case_perms.headed_department(actor)
    profile = getattr(record.user, "staff_profile", None)
    return bool(dept and profile and profile.department_id == dept.pk)


def can_record_arrival(actor):
    return is_officer(actor) or case_perms.is_admin(actor)
