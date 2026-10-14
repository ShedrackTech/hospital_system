"""Who may prescribe, dispense, manage stock, see and cancel prescriptions."""
from cases import permissions as case_perms
from cases.models import Case

from .models import Prescription


def _profile(user):
    return getattr(user, "staff_profile", None)


def is_pharmacy_staff(user):
    """Medical staff in a department marked as the pharmacy."""
    profile = _profile(user)
    return bool(
        user.is_authenticated and profile and profile.category == "medical"
        and profile.department_id and profile.department.is_pharmacy
    )


def is_pharmacy_head(user):
    dept = case_perms.headed_department(user) if user.is_authenticated else None
    return bool(dept and dept.is_pharmacy)


def is_senior_pharmacy(user):
    return is_pharmacy_staff(user) and _profile(user).grade == "senior"


def in_pharmacy_area(user):
    """May open the pharmacy pages at all (admins can look, but cannot dispense)."""
    return is_pharmacy_staff(user) or is_pharmacy_head(user) or case_perms.is_admin(user)


def can_manage_stock(user):
    """Edit the catalogue, receive stock, correct or write off stock."""
    return (
        case_perms.is_admin(user) or is_pharmacy_head(user) or is_senior_pharmacy(user)
    )


def can_receive_stock(user):
    return can_manage_stock(user) or is_pharmacy_staff(user)


def _clinician_for(user, case):
    """The assigned doctor or the head of the case's department."""
    if case.assigned_to_id == user.id:
        return True
    dept = case_perms.headed_department(user)
    return bool(dept and case.department_id == dept.pk)


def can_prescribe(user, case):
    return _clinician_for(user, case) and case.status in (
        Case.Status.ASSIGNED, Case.Status.IN_TREATMENT
    )


def can_dispense(user, prescription):
    return prescription.is_open and (is_pharmacy_staff(user) or is_pharmacy_head(user))


def can_cancel(user, prescription):
    # Only before anything has been handed over
    return prescription.status == Prescription.Status.PRESCRIBED and (
        is_pharmacy_staff(user) or is_pharmacy_head(user)
        or _clinician_for(user, prescription.case)
    )


def can_close(user, prescription):
    return prescription.status == Prescription.Status.PARTLY and (
        is_pharmacy_staff(user) or is_pharmacy_head(user)
    )


def can_view(user, prescription):
    if user.is_patient:
        return prescription.patient.user_id == user.id  # own prescriptions only
    return (
        case_perms.is_admin(user) or in_pharmacy_area(user)
        or _clinician_for(user, prescription.case)
    )


def prescriptions_for_case(user, case):
    """Prescriptions shown on the case page, scoped to what this user may see."""
    prescriptions = case.prescriptions.prefetch_related("items__drug")
    if user.is_patient:
        if case.patient.user_id == user.id:
            return prescriptions
        return prescriptions.none()
    if case_perms.is_admin(user) or in_pharmacy_area(user) or _clinician_for(user, case):
        return prescriptions
    return prescriptions.none()
