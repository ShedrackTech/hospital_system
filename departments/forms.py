from django import forms
from django.db.models import Q

from accounts.models import User

from .models import Department, StaffProfile


class DepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = ("name", "description", "head", "is_general", "is_active")
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class StaffProfileForm(forms.ModelForm):
    class Meta:
        model = StaffProfile
        fields = ("user", "category", "job_title", "department", "grade")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance.pk:
            # The person cannot be changed after the profile is created
            self.fields["user"].disabled = True
        else:
            # Only staff accounts that don't have a profile yet
            self.fields["user"].queryset = User.objects.filter(
                staff_profile__isnull=True
            ).exclude(role=User.Role.PATIENT)

        # Active departments only (keep the current one if it was deactivated)
        department_filter = Q(is_active=True)
        if self.instance.department_id:
            department_filter |= Q(pk=self.instance.department_id)
        self.fields["department"].queryset = Department.objects.filter(
            department_filter
        )
