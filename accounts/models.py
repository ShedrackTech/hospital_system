from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        MAIN_ADMIN = "main_admin", "Main Admin"
        SUB_ADMIN = "sub_admin", "Sub Admin"
        HEAD_OF_DEPARTMENT = "head_of_department", "Head of Department"
        SENIOR_DOCTOR = "senior_doctor", "Senior Doctor"
        DOCTOR = "doctor", "Doctor"
        SENIOR_NURSE = "senior_nurse", "Senior Nurse"
        NURSE = "nurse", "Nurse"
        SENIOR_STAFF = "senior_staff", "Senior Staff"
        STAFF = "staff", "Staff"
        PATIENT = "patient", "Patient"

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.PATIENT)

    # Login ID: patient card number (PAT000001) or staff ID (STF000001).
    # Generated automatically on first save.
    login_id = models.CharField(
        max_length=20, unique=True, null=True, blank=True, editable=False
    )
    phone = models.CharField(max_length=20, blank=True)

    # Who this person reports to:
    # Nurse -> Senior Nurse -> Sub Admin -> Main Admin
    supervisor = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="team",
    )

    class Meta:
        ordering = ["login_id"]

    def __str__(self):
        name = self.get_full_name() or self.username
        return f"{name} ({self.login_id or self.get_role_display()})"

    @property
    def is_patient(self):
        return self.role == self.Role.PATIENT

    @property
    def is_staff_member(self):
        return self.role != self.Role.PATIENT

    def clean(self):
        super().clean()
        if self.pk and self.supervisor_id == self.pk:
            raise ValidationError({"supervisor": "A user cannot supervise themselves."})

    def save(self, *args, **kwargs):
        # Keep role and permission flags consistent
        if self.is_superuser:
            self.role = self.Role.MAIN_ADMIN
        if self.role in (self.Role.MAIN_ADMIN, self.Role.SUB_ADMIN):
            self.is_staff = True
        if self.role == self.Role.PATIENT:
            self.is_staff = False

        super().save(*args, **kwargs)

        if not self.login_id:
            prefix = "PAT" if self.is_patient else "STF"
            self.login_id = f"{prefix}{self.pk:06d}"
            super().save(update_fields=["login_id"])
