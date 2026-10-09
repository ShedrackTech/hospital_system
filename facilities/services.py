"""Admit and discharge. All bed changes go through here."""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from cases.models import Case, CaseEvent
from core.audit import log as audit_log

from .models import Admission, Bed


def admit_patient(case, bed, actor, notes=""):
    with transaction.atomic():
        case = Case.objects.select_for_update().get(pk=case.pk)
        bed = Bed.objects.select_for_update().select_related("ward").get(pk=bed.pk)

        if case.status not in (Case.Status.ASSIGNED, Case.Status.IN_TREATMENT):
            raise ValidationError("Only a case that is assigned or in treatment can be admitted.")
        if case.admissions.filter(discharged_at__isnull=True).exists():
            raise ValidationError("This patient is already admitted.")
        if bed.is_occupied:
            raise ValidationError("This bed is already occupied.")
        ward_dept = bed.ward.department_id
        if ward_dept and ward_dept != case.department_id:
            raise ValidationError("This ward belongs to a different department.")

        admission = Admission.objects.create(
            case=case, bed=bed, admitted_by=actor, notes=notes[:300]
        )
        bed.is_occupied = True
        bed.save(update_fields=["is_occupied"])
        CaseEvent.objects.create(
            case=case, actor=actor, action=CaseEvent.Action.ADMITTED,
            note=f"Admitted to {bed}",
        )
        audit_log(
            actor, "patient_admitted", admission,
            patient=case.patient, detail=f"Admitted to {bed}",
        )
    return admission


def discharge_patient(admission, actor):
    with transaction.atomic():
        admission = (
            Admission.objects.select_for_update(of=("self",))
            .select_related("bed", "case")
            .get(pk=admission.pk)
        )
        if admission.discharged_at is not None:
            raise ValidationError("This patient has already been discharged.")
        admission.discharged_at = timezone.now()
        admission.discharged_by = actor
        admission.save(update_fields=["discharged_at", "discharged_by"])
        Bed.objects.filter(pk=admission.bed_id).update(is_occupied=False)
        CaseEvent.objects.create(
            case=admission.case, actor=actor, action=CaseEvent.Action.DISCHARGED,
            note=f"Discharged from {admission.bed}",
        )
        audit_log(
            actor, "patient_discharged", admission,
            patient=admission.case.patient, detail=f"Discharged from {admission.bed}",
        )
    return admission