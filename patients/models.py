from datetime import date

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


class CardCoverageMixin:
    """Card status for anything that can hold a hospital card."""

    def _card_renewals(self):
        raise NotImplementedError

    @property
    def latest_card_renewal(self):
        return self._card_renewals().order_by("-expires_on", "-id").first()

    @property
    def card_expires_on(self):
        renewal = self.latest_card_renewal
        return renewal.expires_on if renewal else None

    @property
    def card_status(self):
        """'none' (never issued), 'valid' or 'expired'."""
        expires_on = self.card_expires_on
        if expires_on is None:
            return "none"
        return "valid" if expires_on >= timezone.localdate() else "expired"

    @property
    def has_valid_card(self):
        return self.card_status == "valid"


class Family(CardCoverageMixin, models.Model):
    """
    A family card. It only groups patients (billing and front-desk lookup).
    Every member keeps their own card number, login and private record.
    """

    family_number = models.CharField(
        max_length=20, unique=True, null=True, blank=True, editable=False
    )
    name = models.CharField(max_length=150)  # e.g. "Obi family"
    address = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["family_number"]
        verbose_name_plural = "families"

    def __str__(self):
        return f"{self.family_number} - {self.name}"

    def _card_renewals(self):
        return self.card_renewals

    @property
    def head(self):
        return (
            self.members.filter(relationship=Patient.Relationship.HEAD)
            .select_related("user")
            .first()
        )

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.family_number:
            self.family_number = f"FAM{self.pk:06d}"
            super().save(update_fields=["family_number"])


class Patient(CardCoverageMixin, models.Model):
    class Gender(models.TextChoices):
        MALE = "male", "Male"
        FEMALE = "female", "Female"

    class BloodGroup(models.TextChoices):
        A_POS = "A+", "A+"
        A_NEG = "A-", "A-"
        B_POS = "B+", "B+"
        B_NEG = "B-", "B-"
        AB_POS = "AB+", "AB+"
        AB_NEG = "AB-", "AB-"
        O_POS = "O+", "O+"
        O_NEG = "O-", "O-"

    class Relationship(models.TextChoices):
        HEAD = "head", "Head of family"
        SPOUSE = "spouse", "Spouse"
        CHILD = "child", "Child"
        PARENT = "parent", "Parent"
        SIBLING = "sibling", "Sibling"
        OTHER = "other", "Other relative"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="patient_profile",
    )
    family = models.ForeignKey(
        Family,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="members",
    )
    relationship = models.CharField(
        max_length=10, choices=Relationship.choices, blank=True
    )
    date_of_birth = models.DateField()
    gender = models.CharField(max_length=10, choices=Gender.choices)
    address = models.TextField(blank=True)
    blood_group = models.CharField(max_length=3, choices=BloodGroup.choices, blank=True)
    emergency_contact_name = models.CharField(max_length=100, blank=True)
    emergency_contact_phone = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["user__login_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["family"],
                condition=Q(relationship="head"),
                name="one_head_per_family",
                violation_error_message="This family card already has a head.",
            )
        ]

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} ({self.card_number})"

    def _card_renewals(self):
        # A family member is covered by the family card. Anyone else has a single card.
        if self.family_id:
            return self.family.card_renewals
        return self.card_renewals

    @property
    def card_kind(self):
        return "family" if self.family_id else "single"

    @property
    def card_number(self):
        """The card number is the user's login ID (PAT000001)."""
        return self.user.login_id

    @property
    def age(self):
        today = date.today()
        born = self.date_of_birth
        return today.year - born.year - ((today.month, today.day) < (born.month, born.day))

    def clean(self):
        super().clean()
        if self.user_id and not self.user.is_patient:
            raise ValidationError({"user": "This account does not have the Patient role."})
        if self.relationship and not self.family_id:
            raise ValidationError({"relationship": "Choose a family card first."})


class Allergy(models.Model):
    class Severity(models.TextChoices):
        MILD = "mild", "Mild"
        MODERATE = "moderate", "Moderate"
        SEVERE = "severe", "Severe"

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="allergies")
    name = models.CharField(max_length=100)
    reaction = models.CharField(max_length=200, blank=True)
    severity = models.CharField(max_length=10, choices=Severity.choices, default=Severity.MILD)

    class Meta:
        verbose_name_plural = "allergies"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.get_severity_display()})"


class MedicalHistory(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="history")
    condition = models.CharField(max_length=200)
    notes = models.TextField(blank=True)
    date_diagnosed = models.DateField(null=True, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="recorded_history",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "medical history"
        ordering = ["-created_at"]

    def __str__(self):
        return self.condition


class CardType(models.Model):
    """Price and validity of a card. Managed on the Card prices page."""

    class Kind(models.TextChoices):
        SINGLE = "single", "Single card"
        FAMILY = "family", "Family card"

    DEFAULT_VALIDITY_MONTHS = {"single": 6, "family": 12}

    kind = models.CharField(max_length=10, choices=Kind.choices, unique=True)
    name = models.CharField(max_length=50)
    validity_months = models.PositiveSmallIntegerField(
        default=6, validators=[MinValueValidator(1), MaxValueValidator(60)]
    )
    fee = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)]
    )

    def __str__(self):
        return self.name

    @classmethod
    def for_kind(cls, kind):
        card_type, _ = cls.objects.get_or_create(
            kind=kind,
            defaults={
                "name": cls.Kind(kind).label,
                "validity_months": cls.DEFAULT_VALIDITY_MONTHS[kind],
            },
        )
        return card_type

    @classmethod
    def ensure_defaults(cls):
        for kind in cls.Kind.values:
            cls.for_kind(kind)


class CardRenewal(models.Model):
    """One payment for a card: a single card (patient) or a family card (family)."""

    patient = models.ForeignKey(
        Patient,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="card_renewals",
    )
    family = models.ForeignKey(
        Family,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="card_renewals",
    )
    card_type = models.ForeignKey(CardType, on_delete=models.PROTECT, related_name="renewals")
    starts_on = models.DateField()
    expires_on = models.DateField()
    amount_charged = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cards_received",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(patient__isnull=False, family__isnull=True)
                    | Q(patient__isnull=True, family__isnull=False)
                ),
                name="card_renewal_for_one_holder",
            )
        ]

    def __str__(self):
        holder = self.family or self.patient
        return f"{holder} until {self.expires_on}"
