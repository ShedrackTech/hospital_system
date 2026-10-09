from datetime import timedelta

from django import forms
from django.utils import timezone


class FilterForm(forms.Form):
    date = forms.DateField(
        required=False, label="Date", widget=forms.DateInput(attrs={"type": "date"})
    )
    status = forms.ChoiceField(
        required=False,
        choices=[
            ("", "All"), ("unconfirmed", "Unconfirmed"), ("open", "Still clocked in"),
            ("flagged", "Needs review (earlier days)"),
        ],
    )
    q = forms.CharField(
        required=False, label="Search",
        widget=forms.TextInput(attrs={"placeholder": "Name or staff ID"}),
    )


class StaffIdForm(forms.Form):
    staff_id = forms.CharField(
        max_length=20, label="Record arrival by staff ID",
        widget=forms.TextInput(attrs={"placeholder": "e.g. STF000012"}),
    )


class CorrectionForm(forms.Form):
    clock_in = forms.DateTimeField(
        label="Clock in",
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
    )
    clock_out = forms.DateTimeField(
        required=False, label="Clock out (leave empty if still working)",
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
    )
    reason = forms.CharField(max_length=300, label="Reason for the correction")

    def __init__(self, *args, record=None, **kwargs):
        super().__init__(*args, **kwargs)
        if record is not None and not self.is_bound:
            self.initial["clock_in"] = timezone.localtime(record.clock_in)
            if record.clock_out:
                self.initial["clock_out"] = timezone.localtime(record.clock_out)

    def clean(self):
        cleaned = super().clean()
        clock_in, clock_out = cleaned.get("clock_in"), cleaned.get("clock_out")
        if clock_in and clock_out and clock_out <= clock_in:
            self.add_error("clock_out", "Clock out must be after clock in.")
        if clock_in and clock_in > timezone.now() + timedelta(minutes=1):
            self.add_error("clock_in", "Clock in cannot be in the future.")
        return cleaned
