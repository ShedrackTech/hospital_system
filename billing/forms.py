from django import forms

from cases.models import Case

from . import services
from .models import ChargeItem, Payment


class ChargeItemForm(forms.ModelForm):
    class Meta:
        model = ChargeItem
        fields = ["name", "category", "unit_price", "is_active"]


class _ItemChoice(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.name} - \u20a6{obj.unit_price:,.2f}"


class _CaseChoice(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        # No complaint text: the front desk must not read the reason for a visit.
        return f"Case #{obj.pk} ({obj.created_at:%d %b %Y}, {obj.get_status_display()})"


class InvoiceForm(forms.Form):
    case = _CaseChoice(queryset=Case.objects.none(), required=False, empty_label="Not linked to a case")
    note = forms.CharField(max_length=200, required=False)

    def __init__(self, *args, patient=None, **kwargs):
        super().__init__(*args, **kwargs)
        if patient is not None:
            self.fields["case"].queryset = Case.objects.filter(patient=patient).order_by("-created_at")


class InvoiceLineForm(forms.Form):
    item = _ItemChoice(queryset=ChargeItem.objects.none(), required=False, empty_label="Choose an item")
    quantity = forms.IntegerField(
        min_value=1, max_value=services.MAX_QUANTITY, required=False,
        widget=forms.NumberInput(attrs={"placeholder": "1", "min": 1}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["item"].queryset = ChargeItem.objects.filter(is_active=True).order_by("category", "name")

    def clean(self):
        cleaned = super().clean()
        if "item" in self.errors or "quantity" in self.errors:
            return cleaned
        item, quantity = cleaned.get("item"), cleaned.get("quantity")
        if quantity and not item:
            raise forms.ValidationError("Choose an item for this row.")
        if item and not quantity:
            cleaned["quantity"] = 1
        return cleaned


LineFormSet = forms.formset_factory(InvoiceLineForm, extra=6, max_num=services.MAX_LINES, validate_max=True)


class PaymentForm(forms.Form):
    amount = forms.DecimalField(min_value=0.01, max_digits=12, decimal_places=2)
    method = forms.ChoiceField(choices=Payment.Method.choices)
    reference = forms.CharField(max_length=60, required=False)
    note = forms.CharField(max_length=200, required=False)


class VoidForm(forms.Form):
    reason = forms.CharField(max_length=300)
