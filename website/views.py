"""Public website pages. No login needed; nothing here shows patient or private staff data."""
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect
from django.utils import timezone
from django.views.generic import DetailView, FormView, ListView, TemplateView

from departments.models import Department

from .forms import DOCTOR_ROLES, ContactForm
from .models import BlogPost, ContactMessage, DoctorListing, Service, SiteInfo
from .notifications import notify_new_contact_message

MAX_MESSAGES_PER_HOUR = 5  # per IP address


class SiteContextMixin:
    """Adds the hospital's contact details to every public page."""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["site"] = SiteInfo.get()
        context["HOSPITAL_NAME"] = getattr(settings, "HOSPITAL_NAME", "Hospital")
        return context


def public_departments():
    # The general (triage) department is internal, so it is not advertised.
    return Department.objects.filter(is_active=True, is_general=False).order_by("name")


def public_doctors():
    # Opt-in listing, checked again on every request: a doctor who is deactivated,
    # demoted, or has no full name on file disappears from the site automatically.
    return (
        DoctorListing.objects.filter(
            is_listed=True,
            user__is_active=True,
            user__role__in=DOCTOR_ROLES,
            user__staff_profile__category="medical",
        )
        .exclude(user__first_name="", user__last_name="")
        .select_related("user", "user__staff_profile", "user__staff_profile__department")
    )


class HomeView(SiteContextMixin, TemplateView):
    template_name = "website/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["services"] = Service.objects.filter(is_active=True)[:6]
        context["recent_posts"] = BlogPost.objects.public()[:3]
        context["departments"] = public_departments()[:6]
        return context


class AboutView(SiteContextMixin, TemplateView):
    template_name = "website/about.html"


class DepartmentListView(SiteContextMixin, ListView):
    template_name = "website/departments.html"
    context_object_name = "departments"

    def get_queryset(self):
        return public_departments()


class DoctorListView(SiteContextMixin, ListView):
    template_name = "website/doctors.html"
    context_object_name = "listings"

    def get_queryset(self):
        return public_doctors()


class ServiceListView(SiteContextMixin, ListView):
    template_name = "website/services.html"
    context_object_name = "services"

    def get_queryset(self):
        return Service.objects.filter(is_active=True)


class ContactView(SiteContextMixin, FormView):
    template_name = "website/contact.html"
    form_class = ContactForm

    def form_valid(self, form):
        ip = self.request.META.get("REMOTE_ADDR") or None

        # A filled honeypot means a bot: pretend it worked, store nothing.
        if form.cleaned_data.get("company"):
            messages.success(self.request, "Thank you. Your message has been sent.")
            return redirect("website:contact")

        recent = ContactMessage.objects.filter(
            ip_address=ip, created_at__gte=timezone.now() - timedelta(hours=1)
        ).count()
        if ip and recent >= MAX_MESSAGES_PER_HOUR:
            form.add_error(None, "You have sent several messages recently. Please try again later or phone us.")
            return self.form_invalid(form)

        message = form.save(commit=False)
        message.ip_address = ip
        message.save()
        notify_new_contact_message(message)
        messages.success(self.request, "Thank you. Your message has been sent. We will reply as soon as we can.")
        return redirect("website:contact")


class BlogListView(SiteContextMixin, ListView):
    template_name = "website/blog_list.html"
    context_object_name = "posts"
    paginate_by = 9

    def get_category(self):
        category = self.request.GET.get("category")
        return category if category in BlogPost.Category.values else ""

    def get_queryset(self):
        qs = BlogPost.objects.public().select_related("author")
        category = self.get_category()
        return qs.filter(category=category) if category else qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        category = self.get_category()
        context["category_filter"] = category
        context["categories"] = BlogPost.Category.choices
        context["query_extra"] = f"category={category}&" if category else ""
        return context


class BlogDetailView(SiteContextMixin, DetailView):
    template_name = "website/blog_detail.html"
    context_object_name = "post"

    def get_queryset(self):
        # Drafts and future-dated posts return 404, so their existence is not revealed.
        return BlogPost.objects.public().select_related("author")
