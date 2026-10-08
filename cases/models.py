from django.conf import settings
from django.db import models


class Case(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ASSIGNED = "assigned", "Assigned"
        IN_TREATMENT = "in_treatment", "In treatment"
        COMPLETED = "completed", "Completed"

    # Allowed status moves. Re-assignment (pending/assigned -> assigned) is
    # handled by services.assign_case, not by change_status.
    TRANSITIONS = {
        "pending": ["assigned"],
        "assigned": ["in_treatment"],
        "in_treatment": ["completed"],
        "completed": [],
    }

    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.CASCADE, related_name="cases"
    )
    complaint = models.TextField()
    # Department chosen by the patient, or set by triage staff.
    department = models.ForeignKey(
        "departments.Department", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="cases",
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="assigned_cases",
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    # Set when general staff route or confirm the department (triage done).
    routed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="routed_cases",
    )
    routed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "routed_at"])]

    def __str__(self):
        return f"Case #{self.pk} ({self.get_status_display()})"

    @property
    def is_routed(self):
        return self.routed_at is not None

    def allowed_next(self):
        return self.TRANSITIONS.get(self.status, [])


class CaseEvent(models.Model):
    """Immutable history of everything that happens to a case."""

    class Action(models.TextChoices):
        CREATED = "created", "Created"
        ROUTED = "routed", "Routed to department"
        ASSIGNED = "assigned", "Assigned"
        STATUS = "status", "Status changed"
        ADMITTED = "admitted", "Admitted to bed"
        DISCHARGED = "discharged", "Discharged from bed"

    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    action = models.CharField(max_length=20, choices=Action.choices)
    note = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.case_id}: {self.action}"
