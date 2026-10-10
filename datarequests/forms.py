from django import forms

from .models import DataRequest


class RequestForm(forms.Form):
    kind = forms.ChoiceField(choices=DataRequest.Kind.choices, label="What do you need?")
    subject = forms.CharField(max_length=150)
    details = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text="Tell us what is wrong or what you want, and which record it is about.",
    )


class HandleForm(forms.Form):
    status = forms.ChoiceField(choices=[
        (DataRequest.Status.IN_REVIEW, "Being reviewed"),
        (DataRequest.Status.RESOLVED, "Completed"),
        (DataRequest.Status.DECLINED, "Declined"),
    ])
    response = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 4}), required=False,
        label="Answer for the patient",
        help_text="Required when you complete or decline a request. The patient will read it.",
    )


class FilterForm(forms.Form):
    status = forms.ChoiceField(
        required=False,
        choices=[("", "Open requests"), ("all", "All requests")] + list(DataRequest.Status.choices),
    )
    kind = forms.ChoiceField(required=False, choices=[("", "All kinds")] + list(DataRequest.Kind.choices))
    q = forms.CharField(
        required=False, label="Search",
        widget=forms.TextInput(attrs={"placeholder": "Patient name, card number or subject"}),
    )
