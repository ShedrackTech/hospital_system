from django.conf import settings
from django.db import models


class AttendanceRecord(models.Model):
    """
    One period of work for one staff member. Staff clock themselves in and out
    (source "self"), or an attendance officer records them (source "officer").
    Records are never deleted or silently edited: changes go through
    AttendanceCorrection, which keeps the old values and the reason.
    """

    class Source(models.TextChoices):
        SELF = "self", "Self clock-in"
        OFFICER = "officer", "Recorded by attendance officer"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="attendance_records"
    )
    work_date = models.DateField(db_index=True)  # local date of the clock-in
    clock_in = models.DateTimeField()
    clock_out = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.SELF)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    # Set when someone other than the staff member confirms the record
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-clock_in", "-id"]
        indexes = [models.Index(fields=["user", "work_date"])]

    def __str__(self):
        return f"{self.user} {self.work_date}"

    @property
    def is_open(self):
        return self.clock_out is None

    @property
    def is_confirmed(self):
        return self.confirmed_at is not None

    @property
    def hours_display(self):
        if self.clock_out is None:
            return ""
        minutes = int((self.clock_out - self.clock_in).total_seconds() // 60)
        return f"{minutes // 60}h {minutes % 60:02d}m"


class AttendanceCorrection(models.Model):
    """What a record looked like before someone corrected it, and why."""

    record = models.ForeignKey(
        AttendanceRecord, on_delete=models.CASCADE, related_name="corrections"
    )
    corrected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    reason = models.CharField(max_length=300)
    old_clock_in = models.DateTimeField()
    old_clock_out = models.DateTimeField(null=True, blank=True)
    new_clock_in = models.DateTimeField()
    new_clock_out = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Correction of record {self.record_id}"
