"""All billing state changes go through here. Each function runs in a transaction and writes the audit log.

Rule violations raise ValidationError; a person who may not act raises PermissionDenied.
Amounts are never copied into the audit log text beyond the invoice total and payment amount.
"""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from core import audit

from . import permissions
from .models import ChargeItem, Invoice, InvoiceLine, Payment

MAX_LINES = 20
MAX_QUANTITY = 1000
CENT = Decimal("0.01")


def _money(value):
    try:
        amount = Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise ValidationError("Enter a valid amount.")
    return amount


@transaction.atomic
def create_invoice(patient, lines, actor, case=None, note="", request=None):
    """lines is a list of (ChargeItem, quantity). The same item twice is added together."""
    if not permissions.is_cashier(actor):
        raise PermissionDenied
    if not patient.user.is_active:
        raise ValidationError("This patient account is not active.")
    if case is not None and case.patient_id != patient.pk:
        raise ValidationError("That case belongs to a different patient.")

    merged = {}
    for item, quantity in lines:
        if not item.is_active:
            raise ValidationError(f"{item.name} is no longer on the price list.")
        try:
            quantity = int(quantity)
        except (TypeError, ValueError):
            raise ValidationError("Quantity must be a whole number.")
        if quantity < 1 or quantity > MAX_QUANTITY:
            raise ValidationError(f"Quantity must be between 1 and {MAX_QUANTITY}.")
        merged[item.pk] = (item, merged.get(item.pk, (item, 0))[1] + quantity)
    if not merged:
        raise ValidationError("Add at least one item to the invoice.")
    if len(merged) > MAX_LINES:
        raise ValidationError(f"An invoice can have at most {MAX_LINES} different items.")
    for item, quantity in merged.values():
        if quantity > MAX_QUANTITY:
            raise ValidationError(f"Quantity must be between 1 and {MAX_QUANTITY}.")

    total = sum((item.unit_price * quantity for item, quantity in merged.values()), Decimal("0.00"))
    invoice = Invoice.objects.create(
        patient=patient, case=case, note=(note or "").strip()[:200], total=total, issued_by=actor
    )
    invoice.number = f"INV{invoice.pk:06d}"
    invoice.save(update_fields=["number"])
    InvoiceLine.objects.bulk_create(
        InvoiceLine(invoice=invoice, item=item, description=item.name, quantity=quantity, unit_price=item.unit_price)
        for item, quantity in merged.values()
    )
    audit.log(actor, "invoice_created", invoice, patient=patient,
              detail=f"{len(merged)} line(s), total {total}", request=request)
    return invoice


@transaction.atomic
def record_payment(invoice, amount, method, reference, actor, note="", request=None):
    if not permissions.is_cashier(actor):
        raise PermissionDenied
    locked = Invoice.objects.select_for_update().select_related("patient").get(pk=invoice.pk)
    problem = permissions.payment_problem(actor, locked)
    if problem:
        raise ValidationError(problem)

    amount = _money(amount)
    if amount <= 0:
        raise ValidationError("The amount must be more than zero.")
    if amount > locked.balance:
        raise ValidationError("The amount is more than the balance still owed.")
    if method not in Payment.Method.values:
        raise ValidationError("Choose how the money was paid.")
    reference = (reference or "").strip()
    if method != Payment.Method.CASH and not reference:
        raise ValidationError("Enter the transfer or POS reference.")

    payment = Payment.objects.create(
        invoice=locked, amount=amount, method=method, reference=reference[:60],
        note=(note or "").strip()[:200], received_by=actor,
    )
    payment.receipt_number = f"RCT{payment.pk:06d}"
    payment.save(update_fields=["receipt_number"])

    locked.amount_paid = locked.amount_paid + amount
    fields = ["amount_paid"]
    if locked.amount_paid == locked.total:
        locked.status = Invoice.Status.PAID
        locked.paid_at = timezone.now()
        fields += ["status", "paid_at"]
    locked.save(update_fields=fields)
    audit.log(actor, "payment_recorded", locked, patient=locked.patient,
              detail=f"{payment.receipt_number}, {payment.get_method_display()}, amount {amount}", request=request)
    invoice.refresh_from_db()
    return payment


@transaction.atomic
def void_invoice(invoice, actor, reason, request=None):
    if not permissions.can_manage_prices(actor):
        raise PermissionDenied
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("Give a reason for voiding the invoice.")
    locked = Invoice.objects.select_for_update().select_related("patient").get(pk=invoice.pk)
    problem = permissions.void_problem(actor, locked)
    if problem:
        raise ValidationError(problem)
    locked.status = Invoice.Status.VOID
    locked.void_reason = reason[:300]
    locked.voided_by = actor
    locked.voided_at = timezone.now()
    locked.save(update_fields=["status", "void_reason", "voided_by", "voided_at"])
    audit.log(actor, "invoice_voided", locked, patient=locked.patient, request=request)
    invoice.refresh_from_db()
    return locked


@transaction.atomic
def save_item(item, actor, request=None):
    """Create or update a price list entry (item is a ChargeItem, saved here)."""
    if not permissions.can_manage_prices(actor):
        raise PermissionDenied
    created = item.pk is None
    item.save()
    audit.log(actor, "charge_item_created" if created else "charge_item_updated", item, request=request)
    return item
