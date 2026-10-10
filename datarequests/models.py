from django.conf import settings
from django.db import models


class DataRequest(models.Model):
    """
    A patient's request about their own information: a copy, a correction, or deletion.
    Nothing is ever deleted automatically. An administrator reviews the request and
    records the decision and the reason, and every step is written to the audit log.
    """

    class Kind(models.TextChoices):
        ACCESS = "access", "Get a copy of my information"
        CORRECTION = "correction", "Correct my information"
        DELETION = "deletion", "Delete my information"

    class Status(models.TextChoices):
        OPEN = "open", "Received"
        IN_REVIEW = "in_review", "Being reviewed"
        RESOLVED = "resolved", "Completed"
        DECLINED = "declined", "Declined"

    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="data_requests"
    )
    kind = models.CharField(max_length=12, choices=Kind.choices)
    subject = models.CharField(max_length=150)
    details = models.TextField()
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.OPEN, db_index=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    handled_at = models.DateTimeField(null=True, blank=True)
    response = models.TextField(blank=True)  # shown to the patient

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.get_kind_display()} (#{self.pk})"

    @property
    def is_closed(self):
        return self.status in (self.Status.RESOLVED, self.Status.DECLINED)
