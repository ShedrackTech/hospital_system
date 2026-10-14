"""All pharmacy state changes go through here (transactions, row locks, audit log).

Drug names and doses are never copied into the audit log for a patient's prescription;
the log records only that something happened and how many items were involved.
"""
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from cases.models import Case
from core import audit

from .models import (
    Dispensing, Drug, Prescription, PrescriptionItem, StockAdjustment, StockBatch,
)

EXPIRY_WARNING_DAYS = 60


class AllergyWarning(ValidationError):
    """A drug matches an allergy on the patient's record. Needs an explicit acknowledgement."""


# ---- Allergy check -------------------------------------------------------------

def _terms(drug):
    terms = {drug.name.strip().lower()}
    for part in (drug.ingredients or "").split(","):
        part = part.strip().lower()
        if part:
            terms.add(part)
    return {t for t in terms if len(t) >= 3}


def allergy_conflicts(patient, drugs):
    """Return [(drug, allergy), ...] where a recorded allergy matches a drug name or ingredient."""
    allergies = [a for a in patient.allergies.all() if len((a.name or "").strip()) >= 3]
    found = []
    for drug in drugs:
        for allergy in allergies:
            name = allergy.name.strip().lower()
            if any(name in term or term in name for term in _terms(drug)):
                found.append((drug, allergy))
    return found


def _warning_text(conflicts):
    lines = [f"{allergy.name} allergy is recorded for this patient: {drug}" for drug, allergy in conflicts]
    return "; ".join(lines)


# ---- Prescriptions ---------------------------------------------------------------

def _locked(prescription):
    return (
        Prescription.objects.select_for_update(of=("self",))
        .select_related("patient", "case")
        .get(pk=prescription.pk)
    )


def prescribe(case, items, actor, note="", acknowledged=False, request=None):
    """items: list of dicts with drug, dose, frequency, duration_days, quantity, instructions."""
    items = list(items)
    if not items:
        raise ValidationError("Add at least one drug.")
    drugs = [item["drug"] for item in items]
    if len({d.pk for d in drugs}) != len(drugs):
        raise ValidationError("A drug can appear only once on a prescription.")
    with transaction.atomic():
        case = Case.objects.select_for_update(of=("self",)).select_related("patient").get(pk=case.pk)
        if case.status not in (Case.Status.ASSIGNED, Case.Status.IN_TREATMENT):
            raise ValidationError(
                "Medicines can only be prescribed for a case that is assigned or in treatment."
            )
        for item in items:
            if not item["drug"].is_active:
                raise ValidationError(f"{item['drug']} is no longer available.")
            if int(item["quantity"]) < 1 or int(item["duration_days"]) < 1:
                raise ValidationError("Quantity and number of days must be at least 1.")
        conflicts = allergy_conflicts(case.patient, drugs)
        if conflicts and not acknowledged:
            raise AllergyWarning(_warning_text(conflicts))
        prescription = Prescription.objects.create(
            case=case, patient=case.patient, note=(note or "")[:300], prescribed_by=actor,
            allergy_warning_acknowledged=bool(conflicts),
        )
        for item in items:
            PrescriptionItem.objects.create(
                prescription=prescription, drug=item["drug"],
                dose=item["dose"].strip(), frequency=item["frequency"].strip(),
                duration_days=int(item["duration_days"]), quantity=int(item["quantity"]),
                instructions=(item.get("instructions") or "").strip(),
            )
        detail = f"{len(items)} item(s)" + (" (allergy warning acknowledged)" if conflicts else "")
        audit.log(actor, "prescription_created", prescription, patient=case.patient,
                  detail=detail, request=request)
    return prescription


def cancel_prescription(prescription, actor, reason="", request=None):
    with transaction.atomic():
        prescription = _locked(prescription)
        if prescription.status != Prescription.Status.PRESCRIBED:
            raise ValidationError("Only a prescription that has not been dispensed can be cancelled.")
        prescription.cancel_reason = (reason or "")[:300]
        prescription.cancelled_at = timezone.now()
        prescription.status = Prescription.Status.CANCELLED
        prescription.save()
        audit.log(actor, "prescription_cancelled", prescription, patient=prescription.patient,
                  request=request)
    return prescription


def close_prescription(prescription, actor, reason, request=None):
    """End a partly dispensed prescription whose remaining items cannot be supplied."""
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("Say why the remaining items are not being supplied.")
    with transaction.atomic():
        prescription = _locked(prescription)
        if prescription.status != Prescription.Status.PARTLY:
            raise ValidationError("Only a partly dispensed prescription can be closed.")
        prescription.close_reason = reason[:300]
        prescription.closed_by = actor
        prescription.completed_at = timezone.now()
        prescription.status = Prescription.Status.CLOSED
        prescription.save()
        audit.log(actor, "prescription_closed", prescription, patient=prescription.patient,
                  request=request)
    return prescription


def dispense(prescription, quantities, actor, acknowledged=False, request=None):
    """quantities: {item_id: number to hand over now}. All or nothing across the whole prescription."""
    wanted = {int(pk): int(qty) for pk, qty in quantities.items() if qty and int(qty) > 0}
    if not wanted:
        raise ValidationError("Enter a quantity to dispense for at least one drug.")
    today = timezone.localdate()
    with transaction.atomic():
        prescription = _locked(prescription)
        if not prescription.is_open:
            raise ValidationError("This prescription is not open for dispensing.")
        items = list(
            prescription.items.select_for_update(of=("self",)).select_related("drug")
        )
        by_id = {item.pk: item for item in items}
        unknown = set(wanted) - set(by_id)
        if unknown:
            raise ValidationError("A drug that is not on this prescription was selected.")
        conflicts = allergy_conflicts(prescription.patient, [by_id[pk].drug for pk in wanted])
        if conflicts and not acknowledged:
            raise AllergyWarning(_warning_text(conflicts))

        for pk, qty in wanted.items():
            item = by_id[pk]
            if qty > item.quantity_outstanding:
                raise ValidationError(
                    f"{item.drug}: only {item.quantity_outstanding} left to dispense."
                )
            needed = qty
            batches = (
                StockBatch.objects.select_for_update(of=("self",))
                .filter(drug=item.drug, quantity_remaining__gt=0, expiry_date__gte=today)
                .order_by("expiry_date", "id")
            )
            for batch in batches:
                take = min(batch.quantity_remaining, needed)
                Dispensing.objects.create(item=item, batch=batch, quantity=take, dispensed_by=actor)
                batch.quantity_remaining -= take
                batch.save(update_fields=["quantity_remaining"])
                needed -= take
                if needed == 0:
                    break
            if needed:
                # Raising inside the atomic block undoes every change made so far
                raise ValidationError(
                    f"Not enough unexpired stock of {item.drug}: {qty - needed} available, {qty} needed."
                )
            item.quantity_dispensed += qty
            item.save(update_fields=["quantity_dispensed"])

        if all(item.is_complete for item in items):
            prescription.status = Prescription.Status.DISPENSED
            prescription.completed_at = timezone.now()
        else:
            prescription.status = Prescription.Status.PARTLY
        prescription.save()
        detail = f"{len(wanted)} item(s) dispensed" + (" (allergy warning acknowledged)" if conflicts else "")
        audit.log(actor, "prescription_dispensed", prescription, patient=prescription.patient,
                  detail=detail, request=request)
    return prescription


# ---- Stock -----------------------------------------------------------------------------

def receive_stock(drug, batch_number, expiry_date, quantity, actor, notes="", request=None):
    batch_number = (batch_number or "").strip()
    if not batch_number:
        raise ValidationError("Enter the batch number.")
    if not drug.is_active:
        raise ValidationError(f"{drug} is not active in the catalogue.")
    if int(quantity) < 1:
        raise ValidationError("The quantity must be at least 1.")
    if expiry_date <= timezone.localdate():
        raise ValidationError("The expiry date must be in the future.")
    with transaction.atomic():
        if StockBatch.objects.filter(drug=drug, batch_number=batch_number).exists():
            raise ValidationError("This batch number has already been received for this drug.")
        batch = StockBatch.objects.create(
            drug=drug, batch_number=batch_number, expiry_date=expiry_date,
            quantity_received=int(quantity), quantity_remaining=int(quantity),
            notes=(notes or "")[:300], received_by=actor,
        )
        audit.log(actor, "stock_received", batch, detail=f"{drug} x{int(quantity)}", request=request)
    return batch


def adjust_stock(batch, change, reason, note, actor, request=None):
    change = int(change)
    if change == 0:
        raise ValidationError("The change cannot be zero.")
    with transaction.atomic():
        batch = StockBatch.objects.select_for_update(of=("self",)).select_related("drug").get(pk=batch.pk)
        if batch.quantity_remaining + change < 0:
            raise ValidationError(
                f"Only {batch.quantity_remaining} remain in this batch, so it cannot be reduced by {abs(change)}."
            )
        batch.quantity_remaining += change
        batch.save(update_fields=["quantity_remaining"])
        adjustment = StockAdjustment.objects.create(
            batch=batch, change=change, reason=reason, note=(note or "")[:300], adjusted_by=actor,
        )
        audit.log(actor, "stock_adjusted", batch, detail=f"{batch.drug} {change:+d} ({reason})",
                  request=request)
    return adjustment


# ---- Stock overview ---------------------------------------------------------------------

def drug_stock(today=None):
    """Drugs with `available` (unexpired) and `expired_stock` quantities, and a `stock_state`."""
    today = today or timezone.localdate()
    drugs = list(
        Drug.objects.annotate(
            available=Coalesce(Sum("batches__quantity_remaining",
                                   filter=Q(batches__expiry_date__gte=today)), 0),
            expired_stock=Coalesce(Sum("batches__quantity_remaining",
                                       filter=Q(batches__expiry_date__lt=today)), 0),
        )
    )
    for drug in drugs:
        if drug.available == 0:
            drug.stock_state = "out"
        elif drug.reorder_level and drug.available <= drug.reorder_level:
            drug.stock_state = "low"
        else:
            drug.stock_state = "ok"
    return drugs


def low_stock_count():
    return sum(1 for d in drug_stock() if d.is_active and d.stock_state in ("low", "out"))


def expiring_batches(days=EXPIRY_WARNING_DAYS):
    today = timezone.localdate()
    return StockBatch.objects.filter(
        quantity_remaining__gt=0, expiry_date__gte=today,
        expiry_date__lte=today + timedelta(days=days),
    ).select_related("drug")


def expired_batches():
    """Batches past their expiry that still show stock; they should be written off."""
    return StockBatch.objects.filter(
        quantity_remaining__gt=0, expiry_date__lt=timezone.localdate()
    ).select_related("drug")
