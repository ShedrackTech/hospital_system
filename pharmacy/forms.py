from datetime import timedelta

from django import forms
from django.utils import timezone

from .models import Drug, StockAdjustment


class DrugForm(forms.ModelForm):
    class Meta:
        model = Drug
        fields = ("name", "strength", "form", "unit", "ingredients", "drug_class", "reorder_level", "is_active")


class PrescriptionItemForm(forms.Form):
    drug = forms.ModelChoiceField(queryset=Drug.objects.none(), label="Drug")
    dose = forms.CharField(max_length=100, label="Dose", widget=forms.TextInput(attrs={"placeholder": "1 tablet"}))
    frequency = forms.CharField(max_length=100, label="How often", widget=forms.TextInput(attrs={"placeholder": "twice daily"}))
    duration_days = forms.IntegerField(min_value=1, max_value=365, label="Days")
    quantity = forms.IntegerField(min_value=1, max_value=10000, label="Total quantity")
    instructions = forms.CharField(max_length=200, required=False, label="Instructions")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["drug"].queryset = Drug.objects.filter(is_active=True)


class BasePrescriptionFormSet(forms.BaseFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        drugs = [form.cleaned_data["drug"].pk for form in self.forms if form.cleaned_data]
        if not drugs:
            raise forms.ValidationError("Add at least one drug.")
        if len(drugs) != len(set(drugs)):
            raise forms.ValidationError("A drug can appear only once on a prescription.")


PrescriptionFormSet = forms.formset_factory(
    PrescriptionItemForm, formset=BasePrescriptionFormSet, extra=5,
)


class PrescriptionNoteForm(forms.Form):
    note = forms.CharField(max_length=300, required=False, label="Note for the pharmacy")
    acknowledge_allergy = forms.BooleanField(
        required=False, label="I have read the allergy warning and want to go ahead",
    )


class DispenseForm(forms.Form):
    """One whole-number field per drug still waiting to be supplied."""

    acknowledge_allergy = forms.BooleanField(
        required=False, label="I have read the allergy warning and want to go ahead",
    )

    def __init__(self, *args, prescription, **kwargs):
        super().__init__(*args, **kwargs)
        self.item_fields = []
        for item in prescription.items.all():
            if item.quantity_outstanding > 0:
                name = f"item_{item.pk}"
                self.fields[name] = forms.IntegerField(
                    min_value=0, max_value=item.quantity_outstanding, required=False,
                    label=str(item.drug),
                )
                self.item_fields.append((item, name))

    def quantities(self):
        return {int(name[5:]): self.cleaned_data.get(name) or 0 for _, name in self.item_fields}


class ReasonForm(forms.Form):
    reason = forms.CharField(max_length=300, required=False)


class CloseForm(forms.Form):
    reason = forms.CharField(max_length=300)


class ReceiveStockForm(forms.Form):
    drug = forms.ModelChoiceField(queryset=Drug.objects.none())
    batch_number = forms.CharField(max_length=50)
    expiry_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    quantity = forms.IntegerField(min_value=1, max_value=1000000)
    notes = forms.CharField(max_length=300, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["drug"].queryset = Drug.objects.filter(is_active=True)
        self.fields["expiry_date"].widget.attrs["min"] = (timezone.localdate() + timedelta(days=1)).isoformat()


class AdjustStockForm(forms.Form):
    change = forms.IntegerField(
        label="Change", help_text="Use a minus sign to remove stock, for example -10.",
    )
    reason = forms.ChoiceField(choices=StockAdjustment.Reason.choices)
    note = forms.CharField(max_length=300, required=False)
