import os
import uuid

from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils import timezone
from django.utils.text import slugify


def doctor_photo_path(instance, filename):
    """Store photos under a random name so the original file name (often a person's name) is not exposed."""
    extension = os.path.splitext(filename)[1].lower()
    return f"doctor_photos/{uuid.uuid4().hex}{extension}"


def blog_image_path(instance, filename):
    """Same idea for blog pictures: a random name, so the original file name is not exposed."""
    extension = os.path.splitext(filename)[1].lower()
    return f"blog_images/{uuid.uuid4().hex}{extension}"


class SiteInfo(models.Model):
    """One row only: the hospital's public contact details and About text.

    Always read it with SiteInfo.get(); it creates the row on first use.
    """

    about_text = models.TextField(
        blank=True, help_text="Shown on the About page. A blank line starts a new paragraph."
    )
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    emergency_phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    opening_hours = models.CharField(max_length=200, blank=True)
    notify_email = models.EmailField(
        blank=True,
        help_text="New contact messages are also emailed to this address. Leave blank to turn this off. It is never shown on the website.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "site information"
        verbose_name_plural = "site information"

    def __str__(self):
        return "Site information"

    def save(self, *args, **kwargs):
        self.pk = 1  # keep it a single row
        super().save(*args, **kwargs)

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class Service(models.Model):
    """A service the hospital offers, shown on the public Services page."""

    name = models.CharField(max_length=120, unique=True)
    description = models.TextField(blank=True)
    display_order = models.PositiveIntegerField(default=0, help_text="Lower numbers show first.")
    is_active = models.BooleanField(default=True, help_text="Untick to hide it from the website.")

    class Meta:
        ordering = ["display_order", "name"]

    def __str__(self):
        return self.name


class DoctorListing(models.Model):
    """A doctor's opt-in entry on the public Doctors page.

    Only the name, job title, department and the bio written here are ever shown.
    Phone, email and login ID are never shown.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="doctor_listing"
    )
    bio = models.TextField(blank=True)
    photo = models.ImageField(
        upload_to=doctor_photo_path,
        blank=True,
        validators=[FileExtensionValidator(["jpg", "jpeg", "png", "webp"])],
        help_text="JPG, PNG or WebP, up to 2 MB. Only upload a photo the doctor has agreed to publish.",
    )
    display_order = models.PositiveIntegerField(default=0, help_text="Lower numbers show first.")
    is_listed = models.BooleanField(default=True, help_text="Untick to hide from the website.")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_order", "user__last_name", "user__first_name"]

    def __str__(self):
        return self.public_name or str(self.user)

    @property
    def public_name(self):
        return self.user.get_full_name().strip()


class BlogPostQuerySet(models.QuerySet):
    def public(self):
        """Posts visitors may read: published, and not dated in the future."""
        return self.filter(status=BlogPost.Status.PUBLISHED, published_at__lte=timezone.now())


class BlogPost(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"

    class Category(models.TextChoices):
        HEALTH = "health", "Health news and tips"
        HOSPITAL = "hospital", "Hospital news and developments"

    title = models.CharField(max_length=200)
    category = models.CharField(max_length=10, choices=Category.choices, default=Category.HEALTH)
    slug = models.SlugField(max_length=220, unique=True, editable=False)
    summary = models.CharField(max_length=300, blank=True, help_text="One or two lines shown in the blog list.")
    image = models.ImageField(
        upload_to=blog_image_path,
        blank=True,
        validators=[FileExtensionValidator(["jpg", "jpeg", "png", "webp"])],
        help_text="Optional cover picture. JPG, PNG or WebP, up to 5 MB. It is cropped to a wide 16:9 shape automatically.",
    )
    body = models.TextField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="blog_posts"
    )
    published_at = models.DateTimeField(null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = BlogPostQuerySet.as_manager()

    class Meta:
        ordering = ["-published_at", "-created_at"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._unique_slug()
        if self.status == self.Status.PUBLISHED and self.published_at is None:
            self.published_at = timezone.now()
        super().save(*args, **kwargs)

    def _unique_slug(self):
        base = slugify(self.title)[:200] or "post"
        slug, n = base, 2
        while BlogPost.objects.filter(slug=slug).exists():
            slug = f"{base}-{n}"
            n += 1
        return slug

    @property
    def is_public(self):
        return (
            self.status == self.Status.PUBLISHED
            and self.published_at is not None
            and self.published_at <= timezone.now()
        )


class ContactMessage(models.Model):
    """A message sent from the public Contact page: help or information, feedback, or other."""

    class Reason(models.TextChoices):
        HELP = "help", "I need help or information"
        FEEDBACK = "feedback", "Feedback or complaint"
        OTHER = "other", "Something else"

    reason = models.CharField(max_length=12, choices=Reason.choices, default=Reason.HELP)
    name = models.CharField(max_length=100)
    email = models.EmailField()
    social_handle = models.CharField(max_length=100, blank=True)
    subject = models.CharField(max_length=150, blank=True)
    message = models.TextField(max_length=3000)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_handled = models.BooleanField(default=False)
    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="handled_contact_messages"
    )
    handled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.subject} ({self.name})"
