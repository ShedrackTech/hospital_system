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


class ShiftType(models.Model):
    """A named working period, e.g. Morning 07:00-15:00 or Night 19:00-07:00."""

    name = models.CharField(max_length=60, unique=True)
    start_time = models.TimeField()
    end_time = models.TimeField()  # earlier than start_time means the shift ends next day
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["start_time", "name"]

    def __str__(self):
        return f"{self.name} ({self.start_time:%H:%M}-{self.end_time:%H:%M})"

    @property
    def is_overnight(self):
        return self.end_time <= self.start_time


class RosterEntry(models.Model):
    """One staff member planned to work one shift on one day (optionally in a building)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="roster_entries"
    )
    date = models.DateField(db_index=True)  # the day the shift starts
    shift = models.ForeignKey(ShiftType, on_delete=models.PROTECT, related_name="entries")
    building = models.ForeignKey(
        "facilities.Building", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    note = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "shift__start_time", "user_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "date", "shift"], name="one_roster_entry_per_shift"
            )
        ]

    def __str__(self):
        return f"{self.user} {self.date} {self.shift.name}"
