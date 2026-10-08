from django import forms
from django.db.models import Q

from departments.models import Department

from .models import Bed, Building, Ward


class BuildingForm(forms.ModelForm):
    class Meta:
        model = Building
        fields = ("name", "description")
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class WardForm(forms.ModelForm):
    class Meta:
        model = Ward
        fields = ("name", "building", "ward_type", "floor", "department")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].queryset = Department.objects.filter(is_active=True)
        self.fields["department"].required = False
        self.fields["department"].empty_label = "None (shared / general)"


class BulkBedForm(forms.Form):
    """Add several beds to a ward at once, e.g. prefix B, start 1, count 10 -> B1..B10."""

    prefix = forms.CharField(
        max_length=5,
        required=False,
        help_text="Optional, e.g. B gives B1, B2, B3",
    )
    start = forms.IntegerField(min_value=1, max_value=9999, initial=1,
                               label="Start number")
    count = forms.IntegerField(min_value=1, max_value=100, initial=1,
                               label="How many beds")

    def save(self, ward):
        """Create the beds. Numbers that already exist in the ward are skipped."""
        prefix = self.cleaned_data["prefix"].strip()
        start = self.cleaned_data["start"]
        count = self.cleaned_data["count"]

        numbers = [f"{prefix}{n}" for n in range(start, start + count)]
        existing = set(
            Bed.objects.filter(ward=ward, number__in=numbers).values_list(
                "number", flat=True
            )
        )
        new_beds = [Bed(ward=ward, number=n) for n in numbers if n not in existing]
        Bed.objects.bulk_create(new_beds)
        return len(new_beds), len(existing)


class AdmitForm(forms.Form):
    """Pick a free bed: in a shared ward, or in a ward of the case's department."""

    bed = forms.ModelChoiceField(queryset=Bed.objects.none(), label="Bed")
    notes = forms.CharField(max_length=300, required=False)

    def __init__(self, *args, case, **kwargs):
        super().__init__(*args, **kwargs)
        beds = (
            Bed.objects.filter(is_occupied=False)
            .filter(Q(ward__department__isnull=True) | Q(ward__department=case.department))
            .select_related("ward", "ward__building")
            .order_by("ward__building__name", "ward__name", "id")
        )
        self.fields["bed"].queryset = beds
        self.fields["bed"].label_from_instance = (
            lambda b: f"{b.ward.building.name} / {b.ward.name} / Bed {b.number}"
        )
