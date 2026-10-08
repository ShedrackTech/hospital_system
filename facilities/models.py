from django.conf import settings
from django.db import models


class Building(models.Model):
    name = models.CharField(max_length=100, unique=True)  # Block A, Maternity Block
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Ward(models.Model):
    class WardType(models.TextChoices):
        GENERAL = "general", "General Ward"
        PRIVATE = "private", "Private"
        ICU = "icu", "ICU"
        MATERNITY = "maternity", "Maternity"
        PEDIATRIC = "pediatric", "Pediatric"
        ISOLATION = "isolation", "Isolation"

    name = models.CharField(max_length=100)
    building = models.ForeignKey(
        Building, on_delete=models.PROTECT, related_name="wards"
    )
    # Optional: a general ward is shared by all departments.
    # Specialty wards (ICU, Maternity) can be tied to a department.
    department = models.ForeignKey(
        "departments.Department",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="wards",
    )
    ward_type = models.CharField(
        max_length=20, choices=WardType.choices, default=WardType.GENERAL
    )
    floor = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ["building__name", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["building", "name"],
                name="unique_ward_name_per_building",
                violation_error_message="A ward with this name already exists in this building.",
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.building})"


class Bed(models.Model):
    ward = models.ForeignKey(Ward, on_delete=models.CASCADE, related_name="beds")
    number = models.CharField(max_length=10)
    # Kept in sync by facilities.services (admit / discharge)
    is_occupied = models.BooleanField(default=False)

    class Meta:
        ordering = ["ward_id", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["ward", "number"],
                name="unique_bed_number_per_ward",
                violation_error_message="This bed number already exists in this ward.",
            )
        ]

    def __str__(self):
        return f"{self.ward.name} - Bed {self.number}"


class Admission(models.Model):
    """A patient (through their case) occupying a bed. Open until discharged_at is set."""

    case = models.ForeignKey(
        "cases.Case", on_delete=models.PROTECT, related_name="admissions"
    )
    bed = models.ForeignKey(Bed, on_delete=models.PROTECT, related_name="admissions")
    admitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    admitted_at = models.DateTimeField(auto_now_add=True)
    discharged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    discharged_at = models.DateTimeField(null=True, blank=True)
    notes = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-admitted_at"]
        constraints = [
            # The database itself refuses a double-booked bed or a double admission
            models.UniqueConstraint(
                fields=["bed"],
                condition=models.Q(discharged_at__isnull=True),
                name="one_active_admission_per_bed",
            ),
            models.UniqueConstraint(
                fields=["case"],
                condition=models.Q(discharged_at__isnull=True),
                name="one_active_admission_per_case",
            ),
        ]

    def __str__(self):
        return f"Case #{self.case_id} in {self.bed}"

    @property
    def is_active(self):
        return self.discharged_at is None
