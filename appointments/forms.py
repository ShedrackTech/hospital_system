from datetime import timedelta

from django import forms
from django.utils import timezone

from . import permissions, rules
from .models import Appointment, DoctorAvailability


def _doctor_label(user):
    name = user.get_full_name() or user.get_username()
    return f"{name} ({user.staff_profile.department.name})"


class BookingLookupForm(forms.Form):
    """Step 1: which doctor, which day."""

    doctor = forms.ModelChoiceField(queryset=None, label="Doctor")
    date = forms.DateField(label="Date", widget=forms.DateInput(attrs={"type": "date"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["doctor"].queryset = permissions.eligible_doctors()
        self.fields["doctor"].label_from_instance = _doctor_label

    def clean_date(self):
        day = self.cleaned_data["date"]
        today = timezone.localdate()
        if day < today:
            raise forms.ValidationError("Choose today or a later date.")
        if day > today + timedelta(days=rules.MAX_DAYS_AHEAD):
            raise forms.ValidationError(f"Appointments can be booked up to {rules.MAX_DAYS_AHEAD} days ahead.")
        return day


class BookingForm(forms.Form):
    """Step 2: pick one of the free times and say why."""

    slot = forms.ChoiceField(
        label="Time",
        widget=forms.RadioSelect,
        error_messages={"invalid_choice": "That time is no longer available. Please pick another.",
                        "required": "Please choose a time."},
    )
    reason = forms.CharField(
        label="Reason for the visit",
        max_length=rules.REASON_MAX_LENGTH,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(self, *args, slots=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slot"].choices = [
            (
                s.start.isoformat(),
                f"{timezone.localtime(s.start):%H:%M} to {timezone.localtime(s.end):%H:%M}",
            )
            for s in slots
        ]


class CancelForm(forms.Form):
    reason = forms.CharField(
        label="Reason (required for staff)", required=False, max_length=500,
        widget=forms.Textarea(attrs={"rows": 2}),
    )


class AvailabilityForm(forms.Form):
    weekday = forms.TypedChoiceField(choices=DoctorAvailability.Weekday.choices, coerce=int, label="Day")
    start_time = forms.TimeField(label="From", widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"))
    end_time = forms.TimeField(label="To", widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"))
    slot_minutes = forms.TypedChoiceField(
        choices=[(m, f"{m} minutes") for m in rules.SLOT_MINUTES_CHOICES], coerce=int, initial=30,
        label="Length of each visit",
    )
