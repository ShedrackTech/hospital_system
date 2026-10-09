from django.conf import settings
from django.db import models


class LabTest(models.Model):
    """The catalogue of tests the laboratory offers."""

    name = models.CharField(max_length=150, unique=True)
    unit = models.CharField(max_length=30, blank=True)  # e.g. g/dL
    reference_range = models.CharField(max_length=100, blank=True)  # e.g. 12.0 - 16.0
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class LabResult(models.Model):
    """
    One ordered test for one case. Workflow:
    ordered -> resulted (lab staff enter the value) -> released (a clinician or senior
    lab staff approve). A patient sees a result only once it is released.
    """

    class Status(models.TextChoices):
        ORDERED = "ordered", "Ordered"
        RESULTED = "resulted", "Result entered"
        RELEASED = "released", "Released"
        CANCELLED = "cancelled", "Cancelled"

    case = models.ForeignKey(
        "cases.Case", on_delete=models.PROTECT, related_name="lab_results"
    )
    # Always equal to case.patient (set by services); kept for simple, safe filtering
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="lab_results"
    )
    test = models.ForeignKey(LabTest, on_delete=models.PROTECT, related_name="results")
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.ORDERED, db_index=True
    )

    order_note = models.CharField(max_length=300, blank=True)
    ordered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    ordered_at = models.DateTimeField(auto_now_add=True)

    value = models.CharField(max_length=200, blank=True)
    result_notes = models.TextField(blank=True)
    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    resulted_at = models.DateTimeField(null=True, blank=True)

    released_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    released_at = models.DateTimeField(null=True, blank=True)

    cancel_reason = models.CharField(max_length=300, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-ordered_at", "-id"]
        indexes = [models.Index(fields=["patient", "status"])]

    def __str__(self):
        return f"{self.test.name} (case #{self.case_id})"
