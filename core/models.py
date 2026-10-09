from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """
    Append-only record of who did or viewed what, and when.
    Written by core.audit.log(); entries cannot be edited or deleted through the app.
    """

    # Plain string constants (not model choices) so adding a new action later
    # never needs a migration.
    CASE_CREATED = "case_created"
    CASE_ROUTED = "case_routed"
    CASE_ASSIGNED = "case_assigned"
    CASE_STATUS = "case_status"
    CASE_VIEWED = "case_viewed"
    PATIENT_ADMITTED = "patient_admitted"
    PATIENT_DISCHARGED = "patient_discharged"
    PATIENT_RECORD_VIEWED = "patient_record_viewed"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    # Snapshot of the actor's name and ID, so the entry still reads correctly
    # if the account is later changed or removed.
    actor_label = models.CharField(max_length=200, blank=True)
    action = models.CharField(max_length=50, db_index=True)
    target_type = models.CharField(max_length=100, blank=True)  # e.g. "cases.case"
    target_id = models.PositiveBigIntegerField(null=True, blank=True)
    target_repr = models.CharField(max_length=200, blank=True)
    # The patient this entry is about, so "who touched this patient's record" is one query.
    patient = models.ForeignKey(
        "patients.Patient", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    detail = models.CharField(max_length=300, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["patient", "-created_at"]),
            models.Index(fields=["action", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.actor_label or 'system'}: {self.action}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise RuntimeError("Audit log entries cannot be changed.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("Audit log entries cannot be deleted.")
