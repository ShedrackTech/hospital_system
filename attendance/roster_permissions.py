"""Who may plan the duty roster, and whose roster they can see."""
from django.contrib.auth import get_user_model
from django.db.models import Q

from cases import permissions as case_perms

from . import permissions as attendance_perms


def _staff_with_profile():
    User = get_user_model()
    return User.objects.filter(is_active=True, staff_profile__isnull=False).exclude(
        role=User.Role.PATIENT
    )


def manageable_staff(actor):
    """Staff the actor may schedule: everyone for admins, else their department and reports."""
    staff = _staff_with_profile()
    if case_perms.is_admin(actor):
        return staff
    condition = Q(supervisor=actor)
    dept = case_perms.headed_department(actor)
    if dept:
        condition |= Q(staff_profile__department=dept)
    return staff.filter(condition)


def visible_staff(actor):
    """Staff whose schedule the actor may see (officers see everyone, read-only)."""
    if attendance_perms.is_officer(actor):
        return _staff_with_profile()
    return manageable_staff(actor)


def can_open_manager(actor):
    return (
        actor.is_authenticated and not actor.is_patient and (
            case_perms.is_admin(actor)
            or case_perms.headed_department(actor) is not None
            or actor.team.exists()
        )
    )


def can_manage_roster_for(actor, target):
    return manageable_staff(actor).filter(pk=target.pk).exists()
