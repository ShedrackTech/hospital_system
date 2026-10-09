from django import forms

from .models import LabTest


class LabTestForm(forms.ModelForm):
    class Meta:
        model = LabTest
        fields = ("name", "unit", "reference_range", "is_active")


class OrderForm(forms.Form):
    tests = forms.ModelMultipleChoiceField(
        queryset=LabTest.objects.none(), widget=forms.CheckboxSelectMultiple,
        label="Tests to order",
    )
    note = forms.CharField(max_length=300, required=False, label="Note for the lab")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tests"].queryset = LabTest.objects.filter(is_active=True)


class EnterResultForm(forms.Form):
    value = forms.CharField(max_length=200, label="Result")
    notes = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False)


class CancelForm(forms.Form):
    reason = forms.CharField(max_length=300, required=False)
