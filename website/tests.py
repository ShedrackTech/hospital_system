from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import AuditLog
from departments.models import Department, StaffProfile

from .models import BlogPost, ContactMessage, DoctorListing, Service, SiteInfo

User = get_user_model()
PW = "pass12345"
FAST = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


def make_account(username, role="patient", first="", last="", **extra):
    return User.objects.create_user(username=username, password=PW, role=role, first_name=first, last_name=last, **extra)


def make_doctor(username, first="Ada", last="Obi", role="doctor", category="medical", department=None):
    user = make_account(username, role=role, first=first, last=last, phone="08011112222", email=f"{username}@example.com")
    StaffProfile.objects.create(user=user, category=category, job_title="Consultant", department=department)
    return user


def make_post(title="Hand washing", status=BlogPost.Status.PUBLISHED, published_at=None, **extra):
    post = BlogPost(title=title, body="Wash your hands.\n\nOften.", status=status, **extra)
    post.save()
    if published_at is not None:
        BlogPost.objects.filter(pk=post.pk).update(published_at=published_at)
        post.refresh_from_db()
    return post


@FAST
class PublicPagesTests(TestCase):
    def test_public_pages_need_no_login(self):
        for name in ["home", "about", "departments", "doctors", "services", "contact", "blog"]:
            response = self.client.get(reverse(f"website:{name}"))
            self.assertEqual(response.status_code, 200, name)

    def test_login_button_leads_to_portal_login(self):
        response = self.client.get(reverse("website:home"))
        self.assertContains(response, reverse("accounts:login"))

    def test_departments_hide_inactive_and_general(self):
        Department.objects.create(name="Physiotherapy", description="Movement care")
        Department.objects.create(name="Old Unit", is_active=False)
        Department.objects.create(name="General Outpatient", is_general=True)
        response = self.client.get(reverse("website:departments"))
        self.assertContains(response, "Physiotherapy")
        self.assertNotContains(response, "Old Unit")
        self.assertNotContains(response, "General Outpatient")

    def test_inactive_services_are_hidden(self):
        Service.objects.create(name="Dental care")
        Service.objects.create(name="Hidden service", is_active=False)
        response = self.client.get(reverse("website:services"))
        self.assertContains(response, "Dental care")
        self.assertNotContains(response, "Hidden service")

    def test_site_info_shows_in_footer(self):
        info = SiteInfo.get()
        info.phone = "0800-HOSPITAL"
        info.save()
        self.assertContains(self.client.get(reverse("website:contact")), "0800-HOSPITAL")

    def test_site_info_stays_one_row(self):
        SiteInfo.get()
        SiteInfo(phone="1").save()
        SiteInfo(phone="2").save()
        self.assertEqual(SiteInfo.objects.count(), 1)


@FAST
class DoctorListingTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name="Cardiology")

    def listed(self, user, **kwargs):
        return DoctorListing.objects.create(user=user, bio="Heart specialist.", **kwargs)

    def test_listed_doctor_is_shown_without_private_details(self):
        doctor = make_doctor("dr_ada", department=self.dept)
        self.listed(doctor)
        response = self.client.get(reverse("website:doctors"))
        self.assertContains(response, "Ada Obi")
        self.assertContains(response, "Cardiology")
        self.assertContains(response, "Heart specialist.")
        self.assertNotContains(response, doctor.login_id)
        self.assertNotContains(response, "08011112222")
        self.assertNotContains(response, "dr_ada@example.com")

    def test_unlisted_doctor_is_not_shown(self):
        make_doctor("dr_unlisted", first="Hidden", last="Person")
        self.assertNotContains(self.client.get(reverse("website:doctors")), "Hidden Person")

    def test_listing_switched_off_is_not_shown(self):
        self.listed(make_doctor("dr_off", first="Off", last="Switch"), is_listed=False)
        self.assertNotContains(self.client.get(reverse("website:doctors")), "Off Switch")

    def test_deactivated_doctor_disappears(self):
        doctor = make_doctor("dr_gone", first="Gone", last="Away")
        self.listed(doctor)
        doctor.is_active = False
        doctor.save()
        self.assertNotContains(self.client.get(reverse("website:doctors")), "Gone Away")

    def test_demoted_doctor_disappears(self):
        doctor = make_doctor("dr_demoted", first="Demo", last="Ted")
        self.listed(doctor)
        doctor.role = "nurse"
        doctor.save()
        self.assertNotContains(self.client.get(reverse("website:doctors")), "Demo Ted")

    def test_doctor_without_full_name_is_not_shown(self):
        doctor = make_doctor("dr_noname", first="", last="")
        self.listed(doctor)
        response = self.client.get(reverse("website:doctors"))
        self.assertNotContains(response, "dr_noname")


@FAST
class BlogTests(TestCase):
    def test_published_post_is_readable_by_anyone(self):
        post = make_post("Malaria facts")
        self.assertContains(self.client.get(reverse("website:blog")), "Malaria facts")
        self.assertContains(self.client.get(reverse("website:blog_detail", args=[post.slug])), "Wash your hands.")

    def test_draft_is_hidden_and_404(self):
        post = make_post("Secret draft", status=BlogPost.Status.DRAFT)
        self.assertNotContains(self.client.get(reverse("website:blog")), "Secret draft")
        self.assertEqual(self.client.get(reverse("website:blog_detail", args=[post.slug])).status_code, 404)

    def test_future_dated_post_is_hidden(self):
        post = make_post("Coming soon", published_at=timezone.now() + timedelta(days=2))
        self.assertNotContains(self.client.get(reverse("website:blog")), "Coming soon")
        self.assertEqual(self.client.get(reverse("website:blog_detail", args=[post.slug])).status_code, 404)

    def test_body_html_is_escaped(self):
        post = make_post("XSS try")
        BlogPost.objects.filter(pk=post.pk).update(body="<script>alert(1)</script>")
        response = self.client.get(reverse("website:blog_detail", args=[post.slug]))
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertContains(response, "&lt;script&gt;")

    def test_blog_filters_by_category(self):
        make_post("Drink water", category=BlogPost.Category.HEALTH)
        make_post("New maternity wing", category=BlogPost.Category.HOSPITAL)
        url = reverse("website:blog")
        health = self.client.get(url + "?category=health")
        self.assertContains(health, "Drink water")
        self.assertNotContains(health, "New maternity wing")
        hospital = self.client.get(url + "?category=hospital")
        self.assertContains(hospital, "New maternity wing")
        self.assertNotContains(hospital, "Drink water")
        both = self.client.get(url + "?category=bogus")  # unknown value shows everything
        self.assertContains(both, "Drink water")
        self.assertContains(both, "New maternity wing")

    def test_slugs_are_unique(self):
        first = make_post("Same title")
        second = make_post("Same title")
        self.assertNotEqual(first.slug, second.slug)

    def test_publishing_sets_date_once(self):
        post = make_post("Dated", status=BlogPost.Status.DRAFT)
        self.assertIsNone(post.published_at)
        post.status = BlogPost.Status.PUBLISHED
        post.save()
        first_date = post.published_at
        self.assertIsNotNone(first_date)
        post.status = BlogPost.Status.DRAFT
        post.save()
        post.status = BlogPost.Status.PUBLISHED
        post.save()
        self.assertEqual(post.published_at, first_date)


@FAST
class ContactTests(TestCase):
    data = {"reason": "help", "name": "Chika", "email": "chika@example.com", "social_handle": "@chika", "subject": "Visiting hours", "message": "When can I visit?", "company": ""}

    def test_valid_message_is_stored(self):
        response = self.client.post(reverse("website:contact"), self.data)
        self.assertRedirects(response, reverse("website:contact"))
        message = ContactMessage.objects.get()
        self.assertEqual(message.subject, "Visiting hours")
        self.assertFalse(message.is_handled)

    def test_honeypot_is_silently_dropped(self):
        response = self.client.post(reverse("website:contact"), {**self.data, "company": "Spam Ltd"})
        self.assertRedirects(response, reverse("website:contact"))
        self.assertEqual(ContactMessage.objects.count(), 0)

    def test_missing_fields_are_rejected(self):
        response = self.client.post(reverse("website:contact"), {**self.data, "email": "nope"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ContactMessage.objects.count(), 0)

    def test_social_handle_and_default_subject_are_saved(self):
        self.client.post(reverse("website:contact"), {**self.data, "subject": ""})
        message = ContactMessage.objects.get()
        self.assertEqual(message.social_handle, "@chika")
        self.assertEqual(message.subject, "I need help or information")

    def test_social_handle_is_optional(self):
        self.client.post(reverse("website:contact"), {**self.data, "social_handle": ""})
        self.assertEqual(ContactMessage.objects.count(), 1)

    def test_contact_form_has_no_appointment_fields(self):
        response = self.client.get(reverse("website:contact"))
        form = response.context["form"]
        self.assertEqual(list(form.fields), ["reason", "name", "email", "social_handle", "subject", "message", "company"])
        self.assertNotIn("appointment", [value for value, _ in form.fields["reason"].choices])

    def test_too_many_messages_from_one_address_are_blocked(self):
        for _ in range(5):
            self.client.post(reverse("website:contact"), self.data)
        self.assertEqual(ContactMessage.objects.count(), 5)
        response = self.client.post(reverse("website:contact"), self.data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ContactMessage.objects.count(), 5)


@FAST
class ManageAccessTests(TestCase):
    """Only admin roles may use the portal pages that run the website."""

    def setUp(self):
        self.sub_admin = make_account("subadmin", role="sub_admin")
        self.patient = make_account("pat1", role="patient")
        self.doctor = make_doctor("dr_x")
        self.post = make_post("Existing")
        self.service = Service.objects.create(name="Lab")
        self.message = ContactMessage.objects.create(name="A", email="a@example.com", subject="S", message="M")
        self.urls = [
            reverse("website:manage_home"),
            reverse("website:manage_info"),
            reverse("website:manage_posts"),
            reverse("website:manage_post_new"),
            reverse("website:manage_post_edit", args=[self.post.pk]),
            reverse("website:manage_services"),
            reverse("website:manage_service_new"),
            reverse("website:manage_service_edit", args=[self.service.pk]),
            reverse("website:manage_doctors"),
            reverse("website:manage_doctor_new"),
            reverse("website:manage_messages"),
            reverse("website:manage_message", args=[self.message.pk]),
        ]

    def test_anonymous_is_sent_to_login(self):
        for url in self.urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertIn("login", response["Location"], url)

    def test_patient_and_ordinary_staff_get_403(self):
        for account in (self.patient, self.doctor):
            self.client.force_login(account)
            for url in self.urls:
                self.assertEqual(self.client.get(url).status_code, 403, f"{account.username} {url}")

    def test_non_admin_cannot_post(self):
        self.client.force_login(self.doctor)
        response = self.client.post(reverse("website:manage_post_new"), {"title": "X", "category": "health", "body": "Y", "status": "published"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(BlogPost.objects.filter(title="X").count(), 0)
        toggle = self.client.post(reverse("website:manage_message_toggle", args=[self.message.pk]))
        self.assertEqual(toggle.status_code, 403)
        self.message.refresh_from_db()
        self.assertFalse(self.message.is_handled)

    def test_admin_can_open_every_page(self):
        self.client.force_login(self.sub_admin)
        for url in self.urls:
            self.assertEqual(self.client.get(url).status_code, 200, url)


@FAST
class ManageActionTests(TestCase):
    def setUp(self):
        self.admin = make_account("subadmin", role="sub_admin")
        self.client.force_login(self.admin)

    def actions(self):
        # Oldest first, and ignoring the login entries the real audit log adds when a test user logs in.
        entries = AuditLog.objects.exclude(action__startswith="login").order_by("id")
        return list(entries.values_list("action", flat=True))

    def test_create_publish_unpublish_post_is_audited(self):
        response = self.client.post(reverse("website:manage_post_new"),
                                    {"title": "Flu season", "category": "health", "summary": "Tips", "body": "Get vaccinated.", "status": "draft"})
        self.assertRedirects(response, reverse("website:manage_posts"))
        post = BlogPost.objects.get(title="Flu season")
        self.assertEqual(post.author, self.admin)
        self.assertNotContains(self.client.get(reverse("website:blog")), "Flu season")

        edit = reverse("website:manage_post_edit", args=[post.pk])
        self.client.post(edit, {"title": "Flu season", "category": "health", "summary": "Tips", "body": "Get vaccinated.", "status": "published"})
        self.assertContains(self.client.get(reverse("website:blog")), "Flu season")

        self.client.post(edit, {"title": "Flu season", "category": "health", "summary": "Tips", "body": "Get vaccinated.", "status": "draft"})
        self.assertNotContains(self.client.get(reverse("website:blog")), "Flu season")

        self.assertEqual(self.actions(), ["blog_post_created", "blog_post_published", "blog_post_unpublished"])

    def test_audit_never_holds_post_text(self):
        self.client.post(reverse("website:manage_post_new"),
                         {"title": "Title only", "category": "hospital", "summary": "", "body": "PRIVATE BODY TEXT", "status": "draft"})
        for entry in AuditLog.objects.all():
            self.assertNotIn("PRIVATE BODY TEXT", entry.detail)

    def test_service_create_and_edit(self):
        self.client.post(reverse("website:manage_service_new"), {"name": "X-ray", "description": "Imaging", "display_order": 1, "is_active": "on"})
        service = Service.objects.get(name="X-ray")
        self.client.post(reverse("website:manage_service_edit", args=[service.pk]), {"name": "X-ray", "description": "Imaging", "display_order": 1})
        service.refresh_from_db()
        self.assertFalse(service.is_active)
        self.assertEqual(self.actions(), ["service_created", "service_updated"])

    def test_site_info_update(self):
        self.client.post(reverse("website:manage_info"), {"about_text": "We care.", "address": "1 Hospital Rd", "phone": "0803", "emergency_phone": "", "email": "", "opening_hours": ""})
        self.assertEqual(SiteInfo.get().address, "1 Hospital Rd")
        self.assertEqual(self.actions(), ["site_info_updated"])

    def test_doctor_listing_only_offers_eligible_doctors(self):
        good = make_doctor("dr_good", first="Good", last="Doc")
        make_doctor("dr_nurse", first="Nur", last="Se", role="nurse")
        make_doctor("dr_admin_cat", first="Admin", last="Doc", category="admin")
        make_doctor("dr_noname", first="", last="")
        response = self.client.get(reverse("website:manage_doctor_new"))
        choices = list(response.context["form"].fields["user"].queryset)
        self.assertEqual(choices, [good])

    def test_doctor_listing_create_and_audit(self):
        doctor = make_doctor("dr_new", first="New", last="Doc")
        self.client.post(reverse("website:manage_doctor_new"), {"user": doctor.pk, "bio": "Hi", "display_order": 0, "is_listed": "on"})
        self.assertTrue(DoctorListing.objects.filter(user=doctor).exists())
        self.assertEqual(self.actions(), ["doctor_listing_created"])

    def test_ineligible_doctor_cannot_be_posted(self):
        nurse = make_doctor("dr_nurse2", role="nurse")
        self.client.post(reverse("website:manage_doctor_new"), {"user": nurse.pk, "bio": "", "display_order": 0, "is_listed": "on"})
        self.assertEqual(DoctorListing.objects.count(), 0)

    def test_message_view_and_handle_cycle(self):
        message = ContactMessage.objects.create(name="Ngozi", email="n@example.com", subject="Hello", message="Secret enquiry")
        self.assertContains(self.client.get(reverse("website:manage_message", args=[message.pk])), "Secret enquiry")
        toggle = reverse("website:manage_message_toggle", args=[message.pk])
        self.client.post(toggle)
        message.refresh_from_db()
        self.assertTrue(message.is_handled)
        self.assertEqual(message.handled_by, self.admin)
        self.client.post(toggle)
        message.refresh_from_db()
        self.assertFalse(message.is_handled)
        self.assertEqual(self.actions(), ["contact_message_viewed", "contact_message_handled", "contact_message_reopened"])
        for entry in AuditLog.objects.all():
            self.assertNotIn("Secret enquiry", entry.detail)

    def test_toggle_rejects_get(self):
        message = ContactMessage.objects.create(name="N", email="n@example.com", subject="Hi", message="M")
        self.assertEqual(self.client.get(reverse("website:manage_message_toggle", args=[message.pk])).status_code, 405)

    def test_message_list_filters_by_reason(self):
        ContactMessage.objects.create(name="A", email="a@example.com", subject="Help one", message="M", reason="help")
        ContactMessage.objects.create(name="B", email="b@example.com", subject="Feedback one", message="M", reason="feedback")
        url = reverse("website:manage_messages")
        response = self.client.get(url + "?reason=feedback")
        self.assertContains(response, "Feedback one")
        self.assertNotContains(response, "Help one")
        self.assertEqual(self.client.get(url + "?reason=bogus").status_code, 200)  # unknown value is ignored

    def test_message_list_defaults_to_open_only(self):
        ContactMessage.objects.create(name="Open", email="o@example.com", subject="Open one", message="M")
        ContactMessage.objects.create(name="Done", email="d@example.com", subject="Done one", message="M", is_handled=True)
        response = self.client.get(reverse("website:manage_messages"))
        self.assertContains(response, "Open one")
        self.assertNotContains(response, "Done one")
        self.assertContains(self.client.get(reverse("website:manage_messages") + "?show=all"), "Done one")
