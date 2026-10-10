import re

from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.validators import RegexValidator
from django.db import transaction
from django.db.models import Q

from core.mixins import ADMIN_ROLES
from departments.models import Department, StaffProfile

from .models import User
from .staff_rules import assignable_roles

username_validator = RegexValidator(
    r"^[A-Za-z0-9._-]+$",
    "Use only letters, numbers, dots, underscores and hyphens (no spaces).",
)
# PAT000001 / STF000001 are reserved for card numbers and staff IDs
RESERVED_USERNAME = re.compile(r"^(PAT|STF)\d+$", re.IGNORECASE)
phone_validator = RegexValidator(
    r"^\+?[0-9 ]{7,15}$", "Enter a valid phone number, e.g. 08031234567."
)
MEDICAL_ROLES = {
    User.Role.DOCTOR, User.Role.SENIOR_DOCTOR, User.Role.NURSE, User.Role.SENIOR_NURSE,
}


class StaffBaseForm(forms.Form):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    username = forms.CharField(
        min_length=3, max_length=30, validators=[username_validator],
        help_text="3 to 30 characters. Staff can log in with this or with their staff ID.",
    )
    email = forms.EmailField(required=False)
    phone = forms.CharField(max_length=20, validators=[phone_validator])
    role = forms.ChoiceField(choices=[])
    supervisor = forms.ModelChoiceField(
        queryset=User.objects.none(), required=False, empty_label="None"
    )
    category = forms.ChoiceField(choices=StaffProfile.Category.choices)
    job_title = forms.CharField(max_length=100, help_text="e.g. Cleaner, Gateman, Physiotherapist")
    department = forms.ModelChoiceField(
        queryset=Department.objects.none(), required=False, empty_label="None"
    )
    grade = forms.ChoiceField(choices=StaffProfile.Grade.choices)
    attendance_officer = forms.BooleanField(
        required=False, label="Attendance officer",
        help_text="Can record and confirm anyone's attendance (e.g. gateman, HR).",
    )
    records_officer = forms.BooleanField(
        required=False, label="Records officer",
        help_text="Can read and answer patients' data requests (copy, correction, deletion).",
    )

    def __init__(self, *args, actor, target=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        self.target = target
        self.fields["role"].choices = assignable_roles(actor)

        supervisors = User.objects.filter(is_active=True).exclude(role=User.Role.PATIENT)
        if target is not None:
            supervisors = supervisors.exclude(pk=target.pk)
        self.fields["supervisor"].queryset = supervisors.order_by("first_name", "username")

        # Active departments only (keep the current one if it was deactivated since)
        dept_filter = Q(is_active=True)
        profile = getattr(target, "staff_profile", None) if target else None
        if profile and profile.department_id:
            dept_filter |= Q(pk=profile.department_id)
        self.fields["department"].queryset = Department.objects.filter(dept_filter)

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if RESERVED_USERNAME.match(username):
            raise forms.ValidationError(
                "Usernames that look like a card number or staff ID are not allowed."
            )
        taken = User.objects.filter(username__iexact=username)
        if self.target is not None:
            taken = taken.exclude(pk=self.target.pk)
        if taken.exists():
            raise forms.ValidationError("This username is already taken.")
        return username

    def clean_supervisor(self):
        supervisor = self.cleaned_data.get("supervisor")
        if supervisor and self.target is not None:
            node, steps = supervisor, 0
            while node is not None and steps < 50:  # no reporting loops
                if node.pk == self.target.pk:
                    raise forms.ValidationError("This would create a reporting loop.")
                node, steps = node.supervisor, steps + 1
        return supervisor

    def clean(self):
        cleaned = super().clean()
        role, category = cleaned.get("role"), cleaned.get("category")
        if role in MEDICAL_ROLES and category and category != StaffProfile.Category.MEDICAL:
            self.add_error("category", "Doctors and nurses must be in the Medical category.")
        return cleaned

    def profile_values(self):
        d = self.cleaned_data
        return {
            "category": d["category"], "job_title": d["job_title"],
            "department": d["department"], "grade": d["grade"],
            "attendance_officer": d["attendance_officer"],
            "records_officer": d["records_officer"],
        }


class StaffCreateForm(StaffBaseForm):
    password1 = forms.CharField(label="Temporary password", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirm password", widget=forms.PasswordInput)

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2:
            if p1 != p2:
                self.add_error("password2", "The two passwords do not match.")
            else:
                try:
                    validate_password(p1)
                except forms.ValidationError as error:
                    self.add_error("password1", error)
        return cleaned

    @transaction.atomic
    def save(self):
        d = self.cleaned_data
        user = User(
            username=d["username"], first_name=d["first_name"], last_name=d["last_name"],
            email=d["email"], phone=d["phone"], role=d["role"],
            supervisor=d["supervisor"], is_active=True,
        )
        user.is_staff = user.role in ADMIN_ROLES
        user.set_password(d["password1"])
        user.save()  # also generates the staff ID (login_id)
        StaffProfile.objects.create(user=user, **self.profile_values())
        return user


class StaffEditForm(StaffBaseForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        user = self.target
        profile = getattr(user, "staff_profile", None)
        self.initial.update({
            "first_name": user.first_name, "last_name": user.last_name,
            "username": user.username, "email": user.email, "phone": user.phone,
            "role": user.role, "supervisor": user.supervisor_id,
        })
        if profile:
            self.initial.update({
                "category": profile.category, "job_title": profile.job_title,
                "department": profile.department_id, "grade": profile.grade,
                "attendance_officer": profile.attendance_officer,
                "records_officer": profile.records_officer,
            })

    @transaction.atomic
    def save(self):
        """Returns the list of changed fields (for the audit log)."""
        d = self.cleaned_data
        user = self.target
        changed = []
        for field in ("first_name", "last_name", "username", "email", "phone", "role"):
            if getattr(user, field) != d[field]:
                setattr(user, field, d[field])
                changed.append(field)
        new_supervisor_id = d["supervisor"].pk if d["supervisor"] else None
        if user.supervisor_id != new_supervisor_id:
            user.supervisor = d["supervisor"]
            changed.append("supervisor")
        # Keep the staff flag in step with the role, so a demoted sub admin
        # loses admin access immediately.
        user.is_staff = user.role in ADMIN_ROLES
        user.save()

        values = self.profile_values()
        profile = getattr(user, "staff_profile", None)
        if profile is None:
            StaffProfile.objects.create(user=user, **values)
            changed.append("staff profile")
        else:
            for field, value in values.items():
                if field == "department":
                    different = profile.department_id != (value.pk if value else None)
                else:
                    different = getattr(profile, field) != value
                if different:
                    setattr(profile, field, value)
                    changed.append(field)
            profile.save()
        return changed


class StaffPasswordForm(forms.Form):
    password1 = forms.CharField(label="New temporary password", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirm password", widget=forms.PasswordInput)

    def __init__(self, *args, target, **kwargs):
        super().__init__(*args, **kwargs)
        self.target = target

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2:
            if p1 != p2:
                self.add_error("password2", "The two passwords do not match.")
            else:
                try:
                    validate_password(p1, user=self.target)
                except forms.ValidationError as error:
                    self.add_error("password1", error)
        return cleaned


class StaffFilterForm(forms.Form):
    q = forms.CharField(
        required=False, label="Search",
        widget=forms.TextInput(attrs={"placeholder": "Name, staff ID, username or phone"}),
    )
    role = forms.ChoiceField(
        required=False,
        choices=[("", "All roles")]
        + [(v, l) for v, l in User.Role.choices if v != User.Role.PATIENT],
    )
    department = forms.ModelChoiceField(
        queryset=Department.objects.all(), required=False, empty_label="All departments"
    )
    status = forms.ChoiceField(
        required=False,
        choices=[("", "Active and inactive"), ("active", "Active only"),
                 ("inactive", "Inactive only")],
    )
