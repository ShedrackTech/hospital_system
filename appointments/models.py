from django.conf import settings
from django.db import models
from django.db.models import F, Q


class DoctorAvailability(models.Model):
    """A weekly window in which a doctor sees patients, cut into equal slots.

    Example: Monday 09:00 to 12:00 with 30 minute slots gives 6 bookable times.
    A doctor can have several windows on one day (morning and afternoon) as long
    as they do not overlap.
    """

    class Weekday(models.IntegerChoices):
        MONDAY = 0, "Monday"
        TUESDAY = 1, "Tuesday"
        WEDNESDAY = 2, "Wednesday"
        THURSDAY = 3, "Thursday"
        FRIDAY = 4, "Friday"
        SATURDAY = 5, "Saturday"
        SUNDAY = 6, "Sunday"

    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="availability_windows"
    )
    weekday = models.PositiveSmallIntegerField(choices=Weekday.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()
    slot_minutes = models.PositiveSmallIntegerField(default=30)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["doctor_id", "weekday", "start_time"]
        constraints = [
            models.CheckConstraint(
                condition=Q(end_time__gt=F("start_time")), name="availability_end_after_start"
            ),
        ]

    def __str__(self):
        return (
            f"{self.get_weekday_display()} {self.start_time:%H:%M}-{self.end_time:%H:%M} "
            f"({self.slot_minutes} min) {self.doctor}"
        )


class Appointment(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"
        NO_SHOW = "no_show", "No-show"

    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT, related_name="appointments")
    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="doctor_appointments"
    )
    # Snapshot of the doctor's department at booking time, so history does not
    # move if the doctor is transferred later.
    department = models.ForeignKey(
        "departments.Department", on_delete=models.PROTECT, related_name="appointments"
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    reason = models.TextField(max_length=500)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SCHEDULED)
    booked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["starts_at"]
        indexes = [
            models.Index(fields=["doctor", "starts_at"]),
            models.Index(fields=["patient", "starts_at"]),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(ends_at__gt=F("starts_at")), name="appointment_end_after_start"),
            # The database itself refuses a double booking, even if two requests race.
            models.UniqueConstraint(
                fields=["doctor", "starts_at"],
                condition=Q(status="scheduled"),
                name="appointment_one_scheduled_per_doctor_slot",
            ),
            models.UniqueConstraint(
                fields=["patient", "starts_at"],
                condition=Q(status="scheduled"),
                name="appointment_one_scheduled_per_patient_time",
            ),
        ]

    def __str__(self):
        return f"{self.patient} with {self.doctor} at {self.starts_at:%Y-%m-%d %H:%M}"
