"""Who may see or do what on a case. No dependency on other apps' mixins."""
from django.apps import apps

from core.mixins import ADMIN_ROLES

from .models import Case


def _profile(user):
    return getattr(user, "staff_profile", None)


def is_admin(user):
    return user.is_authenticated and (
        user.is_superuser or user.is_staff or getattr(user, "role", None) in ADMIN_ROLES
    )


def is_medical(user):
    p = _profile(user)
    return bool(p and p.category == "medical")


def is_general_staff(user):
    p = _profile(user)
    return bool(is_medical(user) and p.department_id and p.department.is_general)


def headed_department(user):
    return getattr(user, "headed_department", None)


def get_patient(user):
    Patient = apps.get_model("patients", "Patient")
    return Patient.objects.filter(user=user).first()


def can_view(user, case):
    if is_admin(user):
        return True
    if case.patient.user_id == user.id:
        return True
    if case.assigned_to_id == user.id:
        return True
    dept = headed_department(user)
    if dept and case.department_id == dept.pk:
        return True
    if is_general_staff(user) and not case.is_routed:
        return True
    return False


def can_route(user, case):
    return (
        case.status == Case.Status.PENDING
        and not case.is_routed
        and (is_general_staff(user) or is_admin(user))
    )


def can_assign(user, case):
    dept = headed_department(user)
    return bool(
        dept
        and case.is_routed
        and case.department_id == dept.pk
        and case.status in (Case.Status.PENDING, Case.Status.ASSIGNED)
    )


def can_change_status(user, case):
    return case.assigned_to_id == user.id and bool(case.allowed_next()) \
        and case.status != Case.Status.PENDING
