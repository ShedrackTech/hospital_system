from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q

from .models import BlogPost, ContactMessage, DoctorListing, Service, SiteInfo

User = get_user_model()

DOCTOR_ROLES = ("doctor", "senior_doctor")


class ContactForm(forms.ModelForm):
    # Honeypot: real visitors never see or fill this; simple bots do.
    company = forms.CharField(required=False, widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off"}))

    class Meta:
        model = ContactMessage
        fields = ["reason", "name", "email", "social_handle", "subject", "message"]
        labels = {
            "reason": "How can we help?",
            "social_handle": "Social media handle (optional)",
            "subject": "Subject (optional)",
            "message": "Your message",
        }
        help_texts = {"social_handle": "For example @yourname on Instagram, X or Facebook."}
        widgets = {"message": forms.Textarea(attrs={"rows": 6, "maxlength": 3000})}

    def clean(self):
        data = super().clean()
        reason = data.get("reason")
        if reason and not data.get("subject"):
            data["subject"] = ContactMessage.Reason(reason).label
        return data


class BlogPostForm(forms.ModelForm):
    class Meta:
        model = BlogPost
        fields = ["title", "category", "summary", "body", "status"]
        widgets = {"body": forms.Textarea(attrs={"rows": 14})}


class ServiceForm(forms.ModelForm):
    class Meta:
        model = Service
        fields = ["name", "description", "display_order", "is_active"]


class SiteInfoForm(forms.ModelForm):
    class Meta:
        model = SiteInfo
        fields = ["about_text", "address", "phone", "emergency_phone", "email", "opening_hours"]
        widgets = {"about_text": forms.Textarea(attrs={"rows": 8}), "address": forms.Textarea(attrs={"rows": 3})}


class DoctorListingForm(forms.ModelForm):
    class Meta:
        model = DoctorListing
        fields = ["user", "bio", "display_order", "is_listed"]
        labels = {"user": "Doctor"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only active doctors in the Medical category who have a full name on their account.
        eligible = (
            User.objects.filter(is_active=True, role__in=DOCTOR_ROLES, staff_profile__category="medical")
            .exclude(Q(first_name="") & Q(last_name=""))
            .order_by("last_name", "first_name")
        )
        if self.instance.pk:
            # Editing: the doctor cannot be swapped for someone else.
            self.fields["user"].queryset = User.objects.filter(pk=self.instance.user_id)
            self.fields["user"].disabled = True
        else:
            self.fields["user"].queryset = eligible.filter(doctor_listing__isnull=True)
        self.fields["user"].label_from_instance = lambda u: u.get_full_name() or u.get_username()
