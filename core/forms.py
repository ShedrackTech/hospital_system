from django import forms

from .models import AuditLog


def action_label(action):
    """'case_routed' -> 'Case routed'"""
    return action.replace("_", " ").capitalize()


class AuditFilterForm(forms.Form):
    q = forms.CharField(
        required=False,
        label="Search",
        widget=forms.TextInput(
            attrs={"placeholder": "Name, card number, staff ID or keyword"}
        ),
    )
    action = forms.ChoiceField(required=False, label="Action", choices=[])
    date_from = forms.DateField(
        required=False, label="From", widget=forms.DateInput(attrs={"type": "date"})
    )
    date_to = forms.DateField(
        required=False, label="To", widget=forms.DateInput(attrs={"type": "date"})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        actions = (
            AuditLog.objects.order_by("action").values_list("action", flat=True).distinct()
        )
        self.fields["action"].choices = [("", "All actions")] + [
            (a, action_label(a)) for a in actions
        ]
