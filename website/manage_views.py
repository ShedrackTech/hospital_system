"""Portal pages where administrators run the public website. Admin roles only."""
from urllib.parse import urlencode

from django.contrib import messages
from django.db import transaction
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView

from core import audit
from core.mixins import AdminRequiredMixin, FrontDeskRequiredMixin

from .forms import BlogPostForm, DoctorListingForm, ServiceForm, SiteInfoForm
from .models import BlogPost, ContactMessage, DoctorListing, Service, SiteInfo

FORM_TEMPLATE = "website/manage/form.html"


class ManageHomeView(AdminRequiredMixin, TemplateView):
    template_name = "website/manage/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["draft_count"] = BlogPost.objects.filter(status=BlogPost.Status.DRAFT).count()
        context["published_count"] = BlogPost.objects.filter(status=BlogPost.Status.PUBLISHED).count()
        context["open_message_count"] = ContactMessage.objects.filter(is_handled=False).count()
        return context


class AuditedFormMixin:
    """Saves the form and writes the audit entry in one transaction.

    If the audit write fails, the save is rolled back (audit is fail-closed).
    Subclasses set the two action names, title and cancel link.
    """

    template_name = FORM_TEMPLATE
    audit_created = ""
    audit_updated = ""
    page_title = ""
    cancel_url = None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = self.page_title
        context["cancel_url"] = self.cancel_url
        return context

    def audit_detail(self, obj):
        return str(obj)  # a title or name only; never page text or message text

    def audit_action(self, creating, before):
        return self.audit_created if creating else self.audit_updated

    def prepare(self, form, creating):
        """Hook for setting extra fields before the save."""

    def form_valid(self, form):
        creating = form.instance.pk is None
        before = None if creating else type(form.instance).objects.filter(pk=form.instance.pk).first()
        with transaction.atomic():
            self.prepare(form, creating)
            self.object = form.save()
            audit.log(
                self.request.user,
                self.audit_action(creating, before),
                self.object,
                patient=None,
                detail=self.audit_detail(self.object),
                request=self.request,
            )
        messages.success(self.request, "Saved.")
        return HttpResponseRedirect(self.get_success_url())


# ---- Blog posts -------------------------------------------------------------

# Blog posts may be written by admin roles and by administrative-category staff
# (FrontDeskRequiredMixin: "administrative staff and admin roles only"). Everything
# else under /site/ stays admin roles only.

class PostListView(FrontDeskRequiredMixin, ListView):
    template_name = "website/manage/post_list.html"
    context_object_name = "posts"
    paginate_by = 25

    def get_queryset(self):
        return BlogPost.objects.select_related("author").order_by("-updated_at")


class PostFormMixin(AuditedFormMixin):
    model = BlogPost
    form_class = BlogPostForm
    audit_created = "blog_post_created"
    audit_updated = "blog_post_updated"
    cancel_url = reverse_lazy("website:manage_posts")
    success_url = reverse_lazy("website:manage_posts")

    def audit_action(self, creating, before):
        if creating:
            return "blog_post_created"
        if before is not None and before.status != self.object.status:
            if self.object.status == BlogPost.Status.PUBLISHED:
                return "blog_post_published"
            return "blog_post_unpublished"
        return "blog_post_updated"


class PostCreateView(FrontDeskRequiredMixin, PostFormMixin, CreateView):
    page_title = "New blog post"

    def prepare(self, form, creating):
        form.instance.author = self.request.user


class PostUpdateView(FrontDeskRequiredMixin, PostFormMixin, UpdateView):
    page_title = "Edit blog post"


# ---- Services -----------------------------------------------------------------

class ServiceListView(AdminRequiredMixin, ListView):
    template_name = "website/manage/service_list.html"
    context_object_name = "services"
    queryset = Service.objects.all()


class ServiceFormMixin(AuditedFormMixin):
    model = Service
    form_class = ServiceForm
    audit_created = "service_created"
    audit_updated = "service_updated"
    cancel_url = reverse_lazy("website:manage_services")
    success_url = reverse_lazy("website:manage_services")


class ServiceCreateView(AdminRequiredMixin, ServiceFormMixin, CreateView):
    page_title = "New service"


class ServiceUpdateView(AdminRequiredMixin, ServiceFormMixin, UpdateView):
    page_title = "Edit service"


# ---- Doctor listings ------------------------------------------------------------

class DoctorListingListView(AdminRequiredMixin, ListView):
    template_name = "website/manage/doctor_list.html"
    context_object_name = "listings"

    def get_queryset(self):
        return DoctorListing.objects.select_related("user", "user__staff_profile__department")


class DoctorListingFormMixin(AuditedFormMixin):
    model = DoctorListing
    form_class = DoctorListingForm
    audit_created = "doctor_listing_created"
    audit_updated = "doctor_listing_updated"
    cancel_url = reverse_lazy("website:manage_doctors")
    success_url = reverse_lazy("website:manage_doctors")


class DoctorListingCreateView(AdminRequiredMixin, DoctorListingFormMixin, CreateView):
    page_title = "List a doctor on the website"


class DoctorListingUpdateView(AdminRequiredMixin, DoctorListingFormMixin, UpdateView):
    page_title = "Edit doctor listing"


# ---- Site information --------------------------------------------------------------

class SiteInfoUpdateView(AdminRequiredMixin, AuditedFormMixin, UpdateView):
    model = SiteInfo
    form_class = SiteInfoForm
    audit_created = "site_info_updated"
    audit_updated = "site_info_updated"
    page_title = "About text and contact details"
    cancel_url = reverse_lazy("website:manage_home")
    success_url = reverse_lazy("website:manage_home")

    def get_object(self, queryset=None):
        return SiteInfo.get()


# ---- Contact messages --------------------------------------------------------------

class MessageListView(AdminRequiredMixin, ListView):
    template_name = "website/manage/message_list.html"
    context_object_name = "contact_messages"
    paginate_by = 25

    def get_filters(self):
        reason = self.request.GET.get("reason")
        if reason not in ContactMessage.Reason.values:
            reason = ""
        return reason, self.request.GET.get("show") == "all"

    def get_queryset(self):
        reason, show_all = self.get_filters()
        qs = ContactMessage.objects.select_related("handled_by")
        if reason:
            qs = qs.filter(reason=reason)
        return qs if show_all else qs.filter(is_handled=False)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        reason, show_all = self.get_filters()
        params = {}
        if reason:
            params["reason"] = reason
        if show_all:
            params["show"] = "all"
        context["show_all"] = show_all
        context["reason_filter"] = reason
        context["reasons"] = ContactMessage.Reason.choices
        context["query_extra"] = urlencode(params) + "&" if params else ""
        return context


class MessageDetailView(AdminRequiredMixin, DetailView):
    queryset = ContactMessage.objects.select_related("handled_by")
    template_name = "website/manage/message_detail.html"
    context_object_name = "contact_message"

    def get(self, request, *args, **kwargs):
        response = super().get(request, *args, **kwargs)
        audit.log(request.user, "contact_message_viewed", self.object, patient=None,
                  detail=f"Message from a website visitor (id {self.object.pk})", request=request)
        return response


class MessageToggleView(AdminRequiredMixin, View):
    """POST only: mark a message handled, or reopen it."""

    http_method_names = ["post"]

    def post(self, request, pk):
        with transaction.atomic():
            message = get_object_or_404(ContactMessage.objects.select_for_update(), pk=pk)
            if message.is_handled:
                message.is_handled, message.handled_by, message.handled_at = False, None, None
                action = "contact_message_reopened"
            else:
                message.is_handled, message.handled_by, message.handled_at = True, request.user, timezone.now()
                action = "contact_message_handled"
            message.save()
            audit.log(request.user, action, message, patient=None,
                      detail=f"Message id {message.pk}", request=request)
        messages.success(request, "Updated.")
        return redirect("website:manage_message", pk=message.pk)
