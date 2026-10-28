"""Public website pages. No login needed; nothing here shows patient or private staff data.

The home page is one long page: About, Departments, Doctors, Services, Blog and Contact are
sections of it. The old addresses (/about/, /doctors/, ...) still work: they redirect to the section.
"""
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.views.generic import DetailView, FormView, ListView, RedirectView, TemplateView

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


def section_url(anchor):
    """Address of a section of the home page, for example /#contact."""
    return f"{reverse('website:home')}#{anchor}"


def home_sections():
    """Everything the sections of the home page show."""
    return {
        "departments": public_departments(),
        "listings": public_doctors(),
        "services": Service.objects.filter(is_active=True),
        "recent_posts": BlogPost.objects.public()[:3],
    }


class HomeView(SiteContextMixin, TemplateView):
    template_name = "website/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(home_sections())
        context["form"] = ContactForm()
        return context


class SectionRedirectView(RedirectView):
    """Old page addresses send the visitor to that section of the home page."""

    anchor = ""
    permanent = False

    def get_redirect_url(self, *args, **kwargs):
        return section_url(self.anchor)


class ContactView(SiteContextMixin, FormView):
    """Receives the contact form from the home page. A form with mistakes is shown again
    on the home page, with the errors, so the visitor does not lose what they typed."""

    template_name = "website/home.html"
    form_class = ContactForm

    def get(self, request, *args, **kwargs):
        return redirect(section_url("contact"))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(home_sections())
        return context

    def form_valid(self, form):
        ip = self.request.META.get("REMOTE_ADDR") or None

        # A filled honeypot means a bot: pretend it worked, store nothing.
        if form.cleaned_data.get("company"):
            messages.success(self.request, "Thank you. Your message has been sent.")
            return redirect(section_url("contact"))

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
        return redirect(section_url("contact"))


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
