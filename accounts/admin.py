from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .forms import CustomUserChangeForm, CustomUserCreationForm
from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    form = CustomUserChangeForm
    add_form = CustomUserCreationForm

    list_display = (
        "login_id",
        "username",
        "get_full_name",
        "role",
        "supervisor",
        "is_active",
    )
    list_filter = ("role", "is_active", "is_staff")
    search_fields = ("login_id", "username", "first_name", "last_name", "email", "phone")
    ordering = ("login_id",)
    readonly_fields = ("login_id", "last_login", "date_joined")

    fieldsets = UserAdmin.fieldsets + (
        ("Hospital", {"fields": ("login_id", "role", "phone", "supervisor")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "username",
                    "first_name",
                    "last_name",
                    "email",
                    "phone",
                    "role",
                    "supervisor",
                    "password1",
                    "password2",
                ),
            },
        ),
    )
