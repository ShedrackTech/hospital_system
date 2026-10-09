"""Who may order, enter, release, cancel, see and print lab results."""
from cases import permissions as case_perms
from cases.models import Case

from .models import LabResult


def _profile(user):
    return getattr(user, "staff_profile", None)


def is_lab_staff(user):
    profile = _profile(user)
    return bool(
        user.is_authenticated and profile and profile.category == "medical"
        and profile.department_id and profile.department.is_laboratory
    )


def is_senior_lab(user):
    return is_lab_staff(user) and _profile(user).grade == "senior"


def _clinician_for(user, case):
    """The assigned doctor or the head of the case's department."""
    if case.assigned_to_id == user.id:
        return True
    dept = case_perms.headed_department(user)
    return bool(dept and case.department_id == dept.pk)


def can_order(user, case):
    return _clinician_for(user, case) and case.status in (
        Case.Status.ASSIGNED, Case.Status.IN_TREATMENT
    )


def can_enter(user, result):
    return result.status == LabResult.Status.ORDERED and is_lab_staff(user)


def can_release(user, result):
    return result.status == LabResult.Status.RESULTED and (
        _clinician_for(user, result.case) or is_senior_lab(user)
    )


def can_cancel(user, result):
    return result.status == LabResult.Status.ORDERED and (
        is_lab_staff(user) or _clinician_for(user, result.case)
    )


def can_view(user, result):
    if user.is_patient:
        # A patient sees only their own RELEASED results
        return (result.patient.user_id == user.id
                and result.status == LabResult.Status.RELEASED)
    return (case_perms.is_admin(user) or is_lab_staff(user)
            or _clinician_for(user, result.case))


def can_print(user, result):
    return result.status == LabResult.Status.RELEASED and can_view(user, result)


def results_for_case(user, case):
    """Lab results shown on the case page, scoped to what this user may see."""
    results = case.lab_results.select_related("test")
    if user.is_patient:
        if case.patient.user_id == user.id:
            return results.filter(status=LabResult.Status.RELEASED)
        return results.none()
    if case_perms.is_admin(user) or is_lab_staff(user) or _clinician_for(user, case):
        return results
    return results.none()
