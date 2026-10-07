from django import forms
from django.contrib.auth import get_user_model

from departments.models import Department
from .models import Case


class CaseCreateForm(forms.Form):
    complaint = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 4}), label="What is the problem?"
    )
    department = forms.ModelChoiceField(
        queryset=Department.objects.filter(is_general=False),
        required=False, empty_label="Not sure (let the hospital decide)",
    )


class RouteForm(forms.Form):
    department = forms.ModelChoiceField(queryset=Department.objects.all())
    note = forms.CharField(max_length=300, required=False)


class AssignForm(forms.Form):
    assignee = forms.ModelChoiceField(queryset=get_user_model().objects.none(),
                                      label="Assign to")
    note = forms.CharField(max_length=300, required=False)

    def __init__(self, *args, case=None, **kwargs):
        super().__init__(*args, **kwargs)
        User = get_user_model()
        self.fields["assignee"].queryset = User.objects.filter(
            is_active=True,
            staffprofile__category="medical",
            staffprofile__department=case.department,
        ).order_by("first_name", "username")
        self.fields["assignee"].label_from_instance = (
            lambda u: u.get_full_name() or u.username
        )


class StatusForm(forms.Form):
    status = forms.ChoiceField(choices=[])
    note = forms.CharField(max_length=300, required=False)

    def __init__(self, *args, case=None, **kwargs):
        super().__init__(*args, **kwargs)
        labels = dict(Case.Status.choices)
        self.fields["status"].choices = [
            (s, labels[s]) for s in case.allowed_next()
        ]
