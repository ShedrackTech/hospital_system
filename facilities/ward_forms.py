from django import forms

from . import ward_permissions as perms
from .models import Ward


class AssignNursesForm(forms.Form):
    nurses = forms.ModelMultipleChoiceField(
        queryset=None, label="Nurses", widget=forms.SelectMultiple(attrs={"size": 8}),
    )
    ward = forms.ModelChoiceField(queryset=Ward.objects.select_related("building"))

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        nurses = perms.manageable_nurses(actor).order_by("first_name", "username")
        self.fields["nurses"].queryset = nurses
        self.fields["nurses"].label_from_instance = (
            lambda u: f"{u.get_full_name() or u.username} ({u.login_id})"
        )
        self.fields["ward"].label_from_instance = lambda w: f"{w.building.name} / {w.name}"
