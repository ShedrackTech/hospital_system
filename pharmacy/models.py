from django.conf import settings
from django.db import models


class Drug(models.Model):
    """The catalogue of drugs the pharmacy stocks and doctors may prescribe."""

    class Form(models.TextChoices):
        TABLET = "tablet", "Tablet"
        CAPSULE = "capsule", "Capsule"
        SYRUP = "syrup", "Syrup or suspension"
        INJECTION = "injection", "Injection"
        CREAM = "cream", "Cream or ointment"
        DROPS = "drops", "Drops"
        INHALER = "inhaler", "Inhaler"
        OTHER = "other", "Other"

    name = models.CharField(max_length=150)  # e.g. Paracetamol
    strength = models.CharField(max_length=50, blank=True)  # e.g. 500 mg
    form = models.CharField(max_length=12, choices=Form.choices, default=Form.TABLET)
    unit = models.CharField(
        max_length=30, default="unit",
        help_text="What one piece is called when counting stock, e.g. tablet, bottle, vial.",
    )
    ingredients = models.CharField(
        max_length=200, blank=True,
        help_text="Active ingredients, separated by commas. Used to warn about patient allergies.",
    )
    reorder_level = models.PositiveIntegerField(
        default=0, help_text="Flag the drug as low when stock falls to this number. 0 means only flag when it runs out.",
    )
    is_active = models.BooleanField(default=True, help_text="Untick to stop new prescriptions for this drug.")

    class Meta:
        ordering = ["name", "strength"]
        constraints = [
            models.UniqueConstraint(fields=["name", "strength", "form"], name="unique_drug_name_strength_form"),
        ]

    def __str__(self):
        parts = [self.name]
        if self.strength:
            parts.append(self.strength)
        return f"{' '.join(parts)} ({self.get_form_display().lower()})"


class StockBatch(models.Model):
    """One delivery of one drug, with its expiry date. Dispensing uses the earliest expiry first."""

    drug = models.ForeignKey(Drug, on_delete=models.PROTECT, related_name="batches")
    batch_number = models.CharField(max_length=50)
    expiry_date = models.DateField()
    quantity_received = models.PositiveIntegerField()
    quantity_remaining = models.PositiveIntegerField()  # changed only by services
    notes = models.CharField(max_length=300, blank=True)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["expiry_date", "id"]
        constraints = [
            models.UniqueConstraint(fields=["drug", "batch_number"], name="unique_batch_per_drug"),
        ]

    def __str__(self):
        return f"{self.drug.name} batch {self.batch_number}"


class StockAdjustment(models.Model):
    """Every correction or write-off of stock. Never edited or deleted."""

    class Reason(models.TextChoices):
        EXPIRED = "expired", "Expired stock written off"
        DAMAGED = "damaged", "Damaged or lost"
        CORRECTION = "correction", "Count correction"
        OTHER = "other", "Other"

    batch = models.ForeignKey(StockBatch, on_delete=models.PROTECT, related_name="adjustments")
    change = models.IntegerField()  # negative removes stock, positive adds
    reason = models.CharField(max_length=12, choices=Reason.choices)
    note = models.CharField(max_length=300, blank=True)
    adjusted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    adjusted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-adjusted_at", "-id"]


class Prescription(models.Model):
    """
    What a doctor prescribes for one case. Workflow:
    prescribed -> partly_dispensed -> dispensed (or closed, if the rest cannot be supplied).
    A prescription can be cancelled only while nothing has been dispensed.
    """

    class Status(models.TextChoices):
        PRESCRIBED = "prescribed", "Waiting to be dispensed"
        PARTLY = "partly_dispensed", "Partly dispensed"
        DISPENSED = "dispensed", "Dispensed"
        CLOSED = "closed", "Closed (not fully supplied)"
        CANCELLED = "cancelled", "Cancelled"

    OPEN_STATUSES = (Status.PRESCRIBED, Status.PARTLY)

    case = models.ForeignKey("cases.Case", on_delete=models.PROTECT, related_name="prescriptions")
    # Always equal to case.patient (set by services); kept for simple, safe filtering
    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT, related_name="prescriptions")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PRESCRIBED, db_index=True)
    note = models.CharField(max_length=300, blank=True)  # note from the doctor to the pharmacy

    prescribed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    prescribed_at = models.DateTimeField(auto_now_add=True)
    allergy_warning_acknowledged = models.BooleanField(default=False)

    completed_at = models.DateTimeField(null=True, blank=True)  # dispensed or closed
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    close_reason = models.CharField(max_length=300, blank=True)

    cancel_reason = models.CharField(max_length=300, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-prescribed_at", "-id"]
        indexes = [models.Index(fields=["patient", "status"])]

    def __str__(self):
        return f"Prescription #{self.pk} (case #{self.case_id})"

    @property
    def is_open(self):
        return self.status in self.OPEN_STATUSES


class PrescriptionItem(models.Model):
    prescription = models.ForeignKey(Prescription, on_delete=models.CASCADE, related_name="items")
    drug = models.ForeignKey(Drug, on_delete=models.PROTECT, related_name="prescription_items")
    dose = models.CharField(max_length=100)  # e.g. 1 tablet
    frequency = models.CharField(max_length=100)  # e.g. twice daily
    duration_days = models.PositiveSmallIntegerField()
    quantity = models.PositiveIntegerField()  # total to supply
    quantity_dispensed = models.PositiveIntegerField(default=0)  # changed only by services
    instructions = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(fields=["prescription", "drug"], name="one_line_per_drug_per_prescription"),
        ]

    def __str__(self):
        return f"{self.drug} x{self.quantity}"

    @property
    def quantity_outstanding(self):
        return max(self.quantity - self.quantity_dispensed, 0)

    @property
    def is_complete(self):
        return self.quantity_dispensed >= self.quantity


class Dispensing(models.Model):
    """Each handover of stock to a patient, tied to the batch it came from. Never edited or deleted."""

    item = models.ForeignKey(PrescriptionItem, on_delete=models.PROTECT, related_name="dispensings")
    batch = models.ForeignKey(StockBatch, on_delete=models.PROTECT, related_name="dispensings")
    quantity = models.PositiveIntegerField()
    dispensed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    dispensed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["dispensed_at", "id"]
