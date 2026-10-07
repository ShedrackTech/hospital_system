import re

from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.validators import RegexValidator
from django.db import transaction
from django.forms import BaseModelFormSet, modelformset_factory
from django.utils import timezone

from accounts.models import User
from cases.services import create_case
from departments.models import Department

from .cards import issue_card
from .models import CardType, Family, Patient
from .security import CAPTCHA_SESSION_KEY, new_captcha

username_validator = RegexValidator(
    r"^[A-Za-z0-9._-]+$",
    "Use only letters, numbers, dots, underscores and hyphens (no spaces).",
)

# Card numbers and staff IDs look like PAT000001 / STF000001, so usernames
# in that shape are reserved. This keeps every login name unique.
RESERVED_USERNAME = re.compile(r"^(PAT|STF)\d+$", re.IGNORECASE)

phone_validator = RegexValidator(
    r"^\+?[0-9 ]{7,15}$", "Enter a valid phone number, e.g. 08031234567."
)


class PatientRegistrationForm(forms.Form):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    username = forms.CharField(
        min_length=3,
        max_length=30,
        validators=[username_validator],
        help_text="3 to 30 characters. You can log in with this or with your card number.",
    )
    email = forms.EmailField(required=False)
    phone = forms.CharField(max_length=20, validators=[phone_validator])
    date_of_birth = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    gender = forms.ChoiceField(choices=Patient.Gender.choices)
    address = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)
    blood_group = forms.ChoiceField(
        choices=[("", "Not sure")] + list(Patient.BloodGroup.choices), required=False
    )
    emergency_contact_name = forms.CharField(max_length=100, required=False)
    emergency_contact_phone = forms.CharField(
        max_length=20, required=False, validators=[phone_validator]
    )
    # Opens a Pending case when filled in. Required on the public form,
    # optional at the front desk (e.g. when only issuing a card).
    complaint = forms.CharField(
        label="What is the problem?",
        widget=forms.Textarea(attrs={"rows": 3}),
        required=False,
        help_text="Describe the sickness or problem you came for.",
    )
    department = forms.ModelChoiceField(
        label="Department (optional)",
        queryset=Department.objects.filter(is_general=False).order_by("name"),
        required=False,
        empty_label="Not sure (the hospital will decide)",
        help_text="Choose one only if you already know, e.g. Physiotherapy.",
    )
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirm password", widget=forms.PasswordInput)

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if RESERVED_USERNAME.match(username):
            raise forms.ValidationError(
                "Usernames that look like a card number or staff ID are not allowed."
            )
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("This username is already taken.")
        return username

    def clean_date_of_birth(self):
        dob = self.cleaned_data["date_of_birth"]
        if dob > timezone.localdate():
            raise forms.ValidationError("Date of birth cannot be in the future.")
        return dob

    def clean(self):
        cleaned = super().clean()
        password1 = cleaned.get("password1")
        password2 = cleaned.get("password2")
        if password1 and password2:
            if password1 != password2:
                self.add_error("password2", "The two passwords do not match.")
            else:
                try:
                    validate_password(password1)
                except forms.ValidationError as error:
                    self.add_error("password1", error)
        if cleaned.get("department") and not (cleaned.get("complaint") or "").strip():
            self.add_error("complaint", "Describe the problem if you choose a department.")
        return cleaned

    @transaction.atomic
    def save(self):
        data = self.cleaned_data

        user = User(
            username=data["username"],
            first_name=data["first_name"],
            last_name=data["last_name"],
            email=data["email"],
            phone=data["phone"],
            role=User.Role.PATIENT,
        )
        user.set_password(data["password1"])
        user.save()  # also generates the card number (login_id)

        patient = Patient.objects.create(
            user=user,
            date_of_birth=data["date_of_birth"],
            gender=data["gender"],
            address=data["address"],
            blood_group=data["blood_group"],
            emergency_contact_name=data["emergency_contact_name"],
            emergency_contact_phone=data["emergency_contact_phone"],
        )

        complaint = (data.get("complaint") or "").strip()
        if complaint:
            # Front desk staff are recorded as the actor; self-registering patients are not staff
            actor = getattr(self, "registered_by", None) or user
            self.case = create_case(
                patient, complaint, data.get("department"), actor=actor
            )
        return patient


class PublicRegistrationForm(PatientRegistrationForm):
    """
    The public self-registration form: the normal form plus a maths question
    and a hidden honeypot field that real people never fill in.
    """

    captcha = forms.IntegerField(label="Security question")
    website = forms.CharField(
        required=False,
        label="",
        widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off"}),
    )

    def __init__(self, *args, request, **kwargs):
        super().__init__(*args, **kwargs)
        self.request = request
        self.fields["complaint"].required = True
        if self.is_bound:
            # The answer can only be used once
            self._expected_answer = request.session.pop(CAPTCHA_SESSION_KEY, None)
        else:
            self.fields["captcha"].label = new_captcha(request)

    def clean_captcha(self):
        answer = self.cleaned_data["captcha"]
        if self._expected_answer is None or answer != self._expected_answer:
            raise forms.ValidationError("Wrong answer. Please try the new question.")
        return answer

    def clean_website(self):
        if self.cleaned_data["website"]:
            raise forms.ValidationError("Invalid submission.")
        return ""

    def refresh_captcha(self):
        """Give a fresh question when the form is shown again after an error."""
        self.fields["captcha"].label = new_captcha(self.request)
        data = self.data.copy()
        data["captcha"] = ""
        self.data = data


class StaffPatientRegistrationForm(PatientRegistrationForm):
    """Front-desk form: the normal form plus the hospital card choice."""

    card_choice = forms.ChoiceField(
        label="Hospital card",
        initial="single",
        widget=forms.RadioSelect,
        choices=[],  # filled in __init__ with the current prices
    )
    family_number = forms.CharField(
        label="Family card number",
        required=False,
        max_length=20,
        help_text="Only for \"Add to an existing family card\", e.g. FAM000001",
    )
    relationship = forms.ChoiceField(
        label="Relationship to the head of the family",
        required=False,
        choices=[("", "---------")]
        + [c for c in Patient.Relationship.choices if c[0] != Patient.Relationship.HEAD],
    )
    fee_received = forms.BooleanField(
        label="I have received the card fee",
        required=False,
    )

    def __init__(self, *args, registered_by=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.registered_by = registered_by
        self.issued_renewal = None

        single = CardType.for_kind(CardType.Kind.SINGLE)
        family = CardType.for_kind(CardType.Kind.FAMILY)
        self._fees = {"single": single.fee, "new_family": family.fee}
        self.fields["card_choice"].choices = [
            (
                "single",
                f"Single card: \u20a6{single.fee:,.2f} for {single.validity_months} months "
                "(covers only this patient)",
            ),
            (
                "new_family",
                f"New family card: \u20a6{family.fee:,.2f} for {family.validity_months} months "
                "(covers every family member; this patient is the head)",
            ),
            ("join", "Add to an existing family card (no fee, covered by that card)"),
        ]

    def clean(self):
        cleaned = super().clean()
        self._family = None
        choice = cleaned.get("card_choice")

        if choice == "join":
            number = (cleaned.get("family_number") or "").strip()
            if not number:
                self.add_error("family_number", "Enter the family card number.")
            else:
                self._family = Family.objects.filter(family_number__iexact=number).first()
                if self._family is None:
                    self.add_error("family_number", "No family card has this number.")
            if not cleaned.get("relationship"):
                self.add_error("relationship", "Choose the relationship to the head of the family.")

        fee = self._fees.get(choice)
        if fee and fee > 0 and not cleaned.get("fee_received"):
            self.add_error(
                "fee_received",
                f"Confirm that the card fee of \u20a6{fee:,.2f} has been received.",
            )
        return cleaned

    @transaction.atomic
    def save(self):
        patient = super().save()
        choice = self.cleaned_data["card_choice"]

        if choice == "single":
            self.issued_renewal = issue_card(patient, received_by=self.registered_by)
        elif choice == "new_family":
            family = Family.objects.create(
                name=f"{patient.user.last_name} family", address=patient.address
            )
            patient.family = family
            patient.relationship = Patient.Relationship.HEAD
            patient.save(update_fields=["family", "relationship"])
            self.issued_renewal = issue_card(family, received_by=self.registered_by)
        elif choice == "join":
            patient.family = self._family
            patient.relationship = self.cleaned_data["relationship"]
            patient.save(update_fields=["family", "relationship"])
        return patient


class BaseCardPriceFormSet(BaseModelFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        fees = {form.instance.kind: form.cleaned_data["fee"] for form in self.forms}
        single = fees.get(CardType.Kind.SINGLE)
        family = fees.get(CardType.Kind.FAMILY)
        if single is not None and family is not None and family < single:
            raise forms.ValidationError(
                "The family card must cost at least as much as the single card."
            )


CardPriceFormSet = modelformset_factory(
    CardType,
    formset=BaseCardPriceFormSet,
    fields=("fee", "validity_months"),
    extra=0,
)
