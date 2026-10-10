from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class Department(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    head = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="headed_department",
        limit_choices_to=~Q(role="patient"),
    )
    # General department: general doctors/nurses who triage new cases
    is_general = models.BooleanField(default=False)
    # Laboratory department: its medical staff enter and release lab results
    is_laboratory = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class StaffProfile(models.Model):
    class Category(models.TextChoices):
        MEDICAL = "medical", "Medical"
        ADMIN = "admin", "Administrative"
        SUPPORT = "support", "Support"

    class Grade(models.TextChoices):
        JUNIOR = "junior", "Junior"
        SENIOR = "senior", "Senior"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="staff_profile",
    )
    category = models.CharField(max_length=10, choices=Category.choices)
    # e.g. Cleaner, Chef, Gateman, Physiotherapist, Receptionist
    job_title = models.CharField(max_length=100)
    # Optional: a gateman or cleaner may not belong to a clinical department
    department = models.ForeignKey(
        Department,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="staff",
    )
    grade = models.CharField(
        max_length=10, choices=Grade.choices, default=Grade.JUNIOR
    )
    # Attendance officer (e.g. gateman, HR): may record and confirm anyone's attendance
    attendance_officer = models.BooleanField(default=False)
    # Records officer: may read and answer patients' data requests (copy, correction, deletion)
    records_officer = models.BooleanField(default=False)

    class Meta:
        ordering = ["user__login_id"]

    def __str__(self):
        return f"{self.user} - {self.job_title}"

    def clean(self):
        super().clean()
        if self.user_id and self.user.is_patient:
            raise ValidationError({"user": "A patient cannot have a staff profile."})
