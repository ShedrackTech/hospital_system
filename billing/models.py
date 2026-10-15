from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q

MONEY = {"max_digits": 12, "decimal_places": 2}


class ChargeItem(models.Model):
    """One line of the hospital price list. Invoices copy the name and price, so a later price change never alters an old invoice."""

    class Category(models.TextChoices):
        CONSULTATION = "consultation", "Consultation"
        LABORATORY = "laboratory", "Laboratory"
        PHARMACY = "pharmacy", "Pharmacy"
        WARD = "ward", "Ward and admission"
        PROCEDURE = "procedure", "Procedure"
        OTHER = "other", "Other"

    name = models.CharField(
        max_length=120, unique=True,
        help_text="Use a general name. The front desk can read every invoice line, so do not name a diagnosis.",
    )
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.OTHER)
    unit_price = models.DecimalField(**MONEY, validators=[MinValueValidator(Decimal("0.01"))])
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category", "name"]

    def __str__(self):
        return self.name


class Invoice(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        PAID = "paid", "Paid"
        VOID = "void", "Void"

    number = models.CharField(max_length=12, unique=True, null=True, blank=True, editable=False)
    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT, related_name="invoices")
    case = models.ForeignKey(
        "cases.Case", on_delete=models.PROTECT, null=True, blank=True, related_name="invoices"
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    note = models.CharField(max_length=200, blank=True)
    # total and amount_paid are changed only by billing/services.py
    total = models.DecimalField(**MONEY, default=Decimal("0.00"))
    amount_paid = models.DecimalField(**MONEY, default=Decimal("0.00"))
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="invoices_issued")
    issued_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    void_reason = models.CharField(max_length=300, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="invoices_voided"
    )
    voided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-issued_at", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount_paid__gte=0) & Q(amount_paid__lte=F("total")),
                name="invoice_paid_between_zero_and_total",
            ),
        ]

    def __str__(self):
        return self.number or f"Invoice {self.pk}"

    @property
    def balance(self):
        return self.total - self.amount_paid


class InvoiceLine(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(ChargeItem, on_delete=models.PROTECT, null=True, blank=True, related_name="invoice_lines")
    description = models.CharField(max_length=120)  # copied from the price list
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(**MONEY)  # copied from the price list

    class Meta:
        ordering = ["pk"]
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gte=1), name="invoiceline_quantity_positive"),
        ]

    def __str__(self):
        return f"{self.description} x {self.quantity}"

    @property
    def line_total(self):
        return self.unit_price * self.quantity


class Payment(models.Model):
    """One payment received. Never edited or deleted."""

    class Method(models.TextChoices):
        CASH = "cash", "Cash"
        TRANSFER = "transfer", "Bank transfer"
        POS = "pos", "POS card"

    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="payments")
    receipt_number = models.CharField(max_length=12, unique=True, null=True, blank=True, editable=False)
    amount = models.DecimalField(**MONEY)
    method = models.CharField(max_length=10, choices=Method.choices)
    reference = models.CharField(max_length=60, blank=True)
    note = models.CharField(max_length=200, blank=True)
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payments_received")
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["received_at", "pk"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="payment_amount_positive"),
        ]

    def __str__(self):
        return self.receipt_number or f"Payment {self.pk}"
