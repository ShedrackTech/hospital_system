"""Linking an appointment to the case it became. Only the appointment's doctor or the head of its department
may link or unlink, and only a case of the same patient that is assigned or in treatment, assigned to that doctor
or (for the head) in the department. The audit log records the case number only, never the complaint."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from cases.models import Case
from core import audit

from . import permissions
from .models import Appointment


def _owner(user, appt):
    return permissions.is_own_doctor(user, appt) or permissions.is_head_for(user, appt)


def link_problem(user, appt):
    """A message saying why this user cannot link or unlink now, or an empty string when allowed."""
    if not _owner(user, appt):
        return "Only the doctor or the head of the department can link a case."
    if appt.status == Appointment.Status.CANCELLED:
        return "A cancelled appointment cannot be linked to a case."
    return ""


def can_link(user, appt):
    return link_problem(user, appt) == ""


def linkable_cases(user, appt):
    q = Q()
    allowed = False
    if permissions.is_own_doctor(user, appt):
        q |= Q(assigned_to=user)
        allowed = True
    if permissions.is_head_for(user, appt):
        q |= Q(department_id=appt.department_id)
        allowed = True
    if not allowed:
        return Case.objects.none()
    return Case.objects.filter(
        q, patient_id=appt.patient_id,
        status__in=(Case.Status.ASSIGNED, Case.Status.IN_TREATMENT),
    ).order_by("-created_at")


@transaction.atomic
def link_case(appt, case, actor, request=None):
    locked = Appointment.objects.select_for_update(of=("self",)).select_related("patient").get(pk=appt.pk)
    if not _owner(actor, locked):
        raise PermissionDenied
    problem = link_problem(actor, locked)
    if problem:
        raise ValidationError(problem)
    if locked.case_id == case.pk:
        raise ValidationError("This case is already linked to the appointment.")
    if not linkable_cases(actor, locked).filter(pk=case.pk).exists():
        raise ValidationError("That case cannot be linked to this appointment.")
    locked.case = case
    locked.case_linked_by = actor
    locked.case_linked_at = timezone.now()
    locked.save(update_fields=["case", "case_linked_by", "case_linked_at", "updated_at"])
    audit.log(actor, "appointment_case_linked", locked, patient=locked.patient,
              detail=f"Case #{case.pk}", request=request)
    appt.refresh_from_db()
    return locked


@transaction.atomic
def unlink_case(appt, actor, request=None):
    locked = Appointment.objects.select_for_update(of=("self",)).select_related("patient").get(pk=appt.pk)
    if not _owner(actor, locked):
        raise PermissionDenied
    if locked.case_id is None:
        raise ValidationError("No case is linked to this appointment.")
    old = locked.case_id
    locked.case = None
    locked.case_linked_by = None
    locked.case_linked_at = None
    locked.save(update_fields=["case", "case_linked_by", "case_linked_at", "updated_at"])
    audit.log(actor, "appointment_case_unlinked", locked, patient=locked.patient,
              detail=f"Case #{old}", request=request)
    appt.refresh_from_db()
    return locked
