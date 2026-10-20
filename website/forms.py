from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q

from .images import BLOG_FRAME, DOCTOR_FRAME, fit_to_frame
from .models import BlogPost, ContactMessage, DoctorListing, Service, SiteInfo

User = get_user_model()

DOCTOR_ROLES = ("doctor", "senior_doctor")
MAX_PHOTO_BYTES = 2 * 1024 * 1024
MAX_BLOG_IMAGE_BYTES = 5 * 1024 * 1024
ALLOWED_PHOTO_FORMATS = ("JPEG", "PNG", "WEBP")


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
        fields = ["title", "category", "summary", "image", "body", "status"]
        widgets = {"body": forms.Textarea(attrs={"rows": 14})}

    def clean_image(self):
        image = self.cleaned_data.get("image")
        # Only a newly uploaded file has an .image; an unchanged or cleared picture needs no checks.
        if image and hasattr(image, "image"):
            if image.size > MAX_BLOG_IMAGE_BYTES:
                raise forms.ValidationError("The picture is too large. Please use a file under 5 MB.")
            if image.image.format not in ALLOWED_PHOTO_FORMATS:
                raise forms.ValidationError("Please upload a JPG, PNG or WebP picture.")
            return fit_to_frame(image, BLOG_FRAME)
        return image


class ServiceForm(forms.ModelForm):
    class Meta:
        model = Service
        fields = ["name", "description", "display_order", "is_active"]


class SiteInfoForm(forms.ModelForm):
    class Meta:
        model = SiteInfo
        fields = ["about_text", "address", "phone", "emergency_phone", "email", "opening_hours", "notify_email"]
        widgets = {"about_text": forms.Textarea(attrs={"rows": 8}), "address": forms.Textarea(attrs={"rows": 3})}


class DoctorListingForm(forms.ModelForm):
    class Meta:
        model = DoctorListing
        fields = ["user", "bio", "photo", "display_order", "is_listed"]
        labels = {"user": "Doctor"}

    def clean_photo(self):
        photo = self.cleaned_data.get("photo")
        # Only a newly uploaded file has an .image; an unchanged or cleared photo needs no checks.
        if photo and hasattr(photo, "image"):
            if photo.size > MAX_PHOTO_BYTES:
                raise forms.ValidationError("The photo is too large. Please use a file under 2 MB.")
            if photo.image.format not in ALLOWED_PHOTO_FORMATS:
                raise forms.ValidationError("Please upload a JPG, PNG or WebP photo.")
            return fit_to_frame(photo, DOCTOR_FRAME)
        return photo

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
