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
        label="Card number / Staff ID",
        widget=forms.TextInput(
            attrs={"autofocus": True, "placeholder": "e.g. PAT000001 or STF000001"}
        ),
    )
