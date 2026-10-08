"""All case state changes go through here so rules live in one place."""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import Case, CaseEvent


def _log(case, actor, action, note=""):
    CaseEvent.objects.create(case=case, actor=actor, action=action, note=note[:300])


def _lock(case):
    return Case.objects.select_for_update().get(pk=case.pk)


def create_case(patient, complaint, department=None, actor=None):
    complaint = (complaint or "").strip()
    if not complaint:
        raise ValidationError("A complaint is required.")
    with transaction.atomic():
        case = Case.objects.create(
            patient=patient, complaint=complaint, department=department
        )
        _log(case, actor, CaseEvent.Action.CREATED, "Case opened")
    return case


def route_case(case, department, actor, note=""):
    """General staff route (or confirm) the department for a pending case."""
    with transaction.atomic():
        case = _lock(case)
        if case.status != Case.Status.PENDING or case.is_routed:
            raise ValidationError("Only an unrouted pending case can be routed.")
        case.department = department
        case.routed_by = actor
        case.routed_at = timezone.now()
        case.save()
        _log(case, actor, CaseEvent.Action.ROUTED, note or f"Routed to {department}")
    return case


def assign_case(case, assignee, actor, note=""):
    """Department head assigns (or re-assigns before treatment starts)."""
    with transaction.atomic():
        case = _lock(case)
        if not case.is_routed or case.department_id is None:
            raise ValidationError("The case has not been routed to a department.")
        if case.status not in (Case.Status.PENDING, Case.Status.ASSIGNED):
            raise ValidationError("Treatment has started; the case cannot be re-assigned.")
        User = get_user_model()
        valid = User.objects.filter(
            pk=assignee.pk, is_active=True,
            staff_profile__category="medical",
            staff_profile__department=case.department,
        ).exists()
        if not valid:
            raise ValidationError("Assignee must be active medical staff in this department.")
        case.assigned_to = assignee
        case.status = Case.Status.ASSIGNED
        case.save()
        _log(case, actor, CaseEvent.Action.ASSIGNED, note or f"Assigned to {assignee}")
    return case


def change_status(case, new_status, actor, note=""):
    with transaction.atomic():
        case = _lock(case)
        if new_status not in case.allowed_next() or new_status == Case.Status.ASSIGNED:
            raise ValidationError(
                f"Cannot move from {case.get_status_display()} to {new_status}."
            )
        if (new_status == Case.Status.COMPLETED
                and case.admissions.filter(discharged_at__isnull=True).exists()):
            raise ValidationError("Discharge the patient from the bed before completing the case.")
        case.status = new_status
        case.save()
        _log(case, actor, CaseEvent.Action.STATUS, note or f"Status: {new_status}")
    return case
