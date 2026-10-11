from django import forms
from django.contrib.auth.forms import (
    AuthenticationForm,
    UserChangeForm,
    UserCreationForm,
)

from .models import User


class CustomUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = (
            "username",
            "first_name",
            "last_name",
            "email",
            "phone",
            "role",
            "supervisor",
        )


class CustomUserChangeForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = User
        fields = "__all__"


class LoginForm(AuthenticationForm):
    username = forms.CharField(
        label="Username, card number or staff ID",
        widget=forms.TextInput(
            attrs={"autofocus": True, "placeholder": "e.g. ada, PAT000001 or STF000001"}
        ),
    )

    def clean(self):
        # Show a clear message when the account is locked (the same message for a real
        # account and for an ID that does not exist, so nothing is revealed).
        from core import lockout

        username = self.cleaned_data.get("username")
        if username:
            wait = lockout.minutes_left(username)
            if wait:
                lockout.note_blocked(username, self.request)
                raise forms.ValidationError(
                    "Too many failed attempts. Please try again in "
                    f"{wait} minute{'s' if wait != 1 else ''}.",
                    code="locked",
                )
        return super().clean()
