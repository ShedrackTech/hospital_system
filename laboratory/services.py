"""All lab state changes go through here (transactions, row locks, audit log)."""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from cases.models import Case
from core import audit

from .models import LabResult


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
