"""Who may assign nurses to wards."""
from django.contrib.auth import get_user_model
from django.db.models import Q

from cases import permissions as case_perms


def manageable_nurses(actor):
    """Active nurses the actor may assign: all for admins; a department head's own team."""
    User = get_user_model()
    nurses = User.objects.filter(
        is_active=True,
        role__in=[User.Role.NURSE, User.Role.SENIOR_NURSE],
        staff_profile__category="medical",
    )
    if case_perms.is_admin(actor):
        return nurses
    condition = Q(supervisor=actor)
    dept = case_perms.headed_department(actor)
    if dept:
        condition |= Q(staff_profile__department=dept)
    return nurses.filter(condition)


def can_open_manager(actor):
    return actor.is_authenticated and not actor.is_patient and (
        case_perms.is_admin(actor) or case_perms.headed_department(actor) is not None
    )
