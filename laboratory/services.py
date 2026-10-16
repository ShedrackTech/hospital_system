"""All lab state changes go through here (transactions, row locks, audit log)."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from cases.models import Case
from core import audit
from notifications import services as notifications

from . import permissions as perms
from .models import LabResult, LabResultAmendment


def _locked(result):
    return (
        LabResult.objects.select_for_update(of=("self",))
        .select_related("test", "patient", "case")
        .get(pk=result.pk)
    )


def order_tests(case, tests, actor, note="", request=None):
    tests = list(tests)
    if not tests:
        raise ValidationError("Choose at least one test.")
    with transaction.atomic():
        case = Case.objects.select_for_update().select_related("patient").get(pk=case.pk)
        if case.status not in (Case.Status.ASSIGNED, Case.Status.IN_TREATMENT):
            raise ValidationError(
                "Tests can only be ordered for a case that is assigned or in treatment."
            )
        results = []
        for test in tests:
            if not test.is_active:
                raise ValidationError(f"{test.name} is no longer available.")
            result = LabResult.objects.create(
                case=case, patient=case.patient, test=test,
                order_note=(note or "")[:300], ordered_by=actor,
            )
            audit.log(actor, "lab_ordered", result, patient=case.patient,
                      detail=test.name, request=request)
            results.append(result)
    return results


def enter_result(result, value, notes, actor, request=None):
    value = (value or "").strip()
    if not value:
        raise ValidationError("Enter the result value.")
    with transaction.atomic():
        result = _locked(result)
        if result.status != LabResult.Status.ORDERED:
            raise ValidationError("A result can only be entered for an ordered test.")
        result.value = value
        result.result_notes = (notes or "").strip()
        result.entered_by = actor
        result.resulted_at = timezone.now()
        result.status = LabResult.Status.RESULTED
        result.save()
        # The result value itself is never copied into the audit log
        audit.log(actor, "lab_result_entered", result, patient=result.patient,
                  detail=result.test.name, request=request)
    return result


def release_result(result, actor, request=None):
    with transaction.atomic():
        result = _locked(result)
        if result.status != LabResult.Status.RESULTED:
            raise ValidationError("Only a result that has been entered can be released.")
        result.released_by = actor
        result.released_at = timezone.now()
        result.status = LabResult.Status.RELEASED
        result.save()
        audit.log(actor, "lab_result_released", result, patient=result.patient,
                  detail=result.test.name, request=request)
    return result


def amend_result(result, value, notes, reason, actor, request=None):
    """Correct a released result. The earlier value is kept, the patient is told, and so is the assigned doctor
    (unless they made the amendment). Neither the values nor the reason are copied into the audit log or a notification."""
    value = (value or "").strip()
    notes = (notes or "").strip()
    reason = (reason or "").strip()
    if not value:
        raise ValidationError("Enter the corrected result value.")
    if not reason:
        raise ValidationError("Give a reason for the amendment.")
    with transaction.atomic():
        result = _locked(result)
        if result.status != LabResult.Status.RELEASED:
            raise ValidationError("Only a released result can be amended.")
        if not perms.can_amend(actor, result):
            raise PermissionDenied
        if value == result.value and notes == (result.result_notes or "").strip():
            raise ValidationError("Nothing has changed. Change the result or the notes first.")
        LabResultAmendment.objects.create(
            result=result, old_value=result.value, old_notes=result.result_notes,
            new_value=value, new_notes=notes, reason=reason[:300], amended_by=actor,
        )
        result.value = value
        result.result_notes = notes
        result.amended_at = timezone.now()
        result.save()
        audit.log(actor, "lab_result_amended", result, patient=result.patient,
                  detail=result.test.name, request=request)

        link = reverse("laboratory:result", args=[result.pk])
        notifications.notify(
            result.patient.user, "lab_amended", "A lab result was updated",
            "One of your lab results was corrected. Open it to see what changed.", link,
        )
        doctor = result.case.assigned_to
        if doctor is not None and doctor.pk != actor.pk:
            notifications.notify(
                doctor, "lab_amended", "A released lab result was amended",
                f"A result on case #{result.case_id} was corrected.", link,
            )
    return result


def cancel_result(result, actor, reason="", request=None):
    with transaction.atomic():
        result = _locked(result)
        if result.status != LabResult.Status.ORDERED:
            raise ValidationError("Only a test that has not been resulted can be cancelled.")
        result.cancel_reason = (reason or "")[:300]
        result.cancelled_at = timezone.now()
        result.status = LabResult.Status.CANCELLED
        result.save()
        audit.log(actor, "lab_result_cancelled", result, patient=result.patient,
                  detail=result.test.name, request=request)
    return result
