from django import forms
from django.utils import timezone

from facilities.models import Building

from . import roster_permissions as roster_perms
from .models import ShiftType


class ShiftTypeForm(forms.ModelForm):
    class Meta:
        model = ShiftType
        fields = ("name", "start_time", "end_time", "is_active")
        widgets = {
            "start_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "end_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
        }
        help_texts = {"end_time": "If this is earlier than the start, the shift ends the next day."}


class AssignShiftForm(forms.Form):
    staff = forms.ModelMultipleChoiceField(
        queryset=None, label="Staff", widget=forms.SelectMultiple(attrs={"size": 8}),
    )
    shift = forms.ModelChoiceField(queryset=ShiftType.objects.filter(is_active=True))
    date_from = forms.DateField(label="From", widget=forms.DateInput(attrs={"type": "date"}))
    date_to = forms.DateField(label="To", widget=forms.DateInput(attrs={"type": "date"}))
    building = forms.ModelChoiceField(
        queryset=Building.objects.all(), required=False, empty_label="Not specified",
        label="Work area",
    )
    note = forms.CharField(max_length=200, required=False)

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        staff = roster_perms.manageable_staff(actor).order_by("first_name", "username")
        self.fields["staff"].queryset = staff
        self.fields["staff"].label_from_instance = (
            lambda u: f"{u.get_full_name() or u.username} ({u.login_id})"
        )
        self.fields["shift"].queryset = ShiftType.objects.filter(is_active=True)
        self.initial.setdefault("date_from", timezone.localdate())
        self.initial.setdefault("date_to", timezone.localdate())
