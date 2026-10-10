from django.test import TestCase, override_settings
from django.urls import reverse

from cases.tests import PW, make_patient, make_user
from core.models import AuditLog
from departments.models import StaffProfile

from . import services
from .models import DataRequest

FAST = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


def person(username, role, category, records_officer=False):
    user = make_user(username)
    user.role = role
    user.save()
    StaffProfile.objects.create(user=user, category=category, job_title="Staff",
                                department=None, grade="junior",
                                records_officer=records_officer)
    return user


@FAST
class RecordsOfficerTests(TestCase):
    def setUp(self):
        self.officer = person("officer", "staff", "admin", records_officer=True)
        self.clerk = person("clerk", "staff", "admin")           # administrative, not an officer
        self.doc = person("doc", "doctor", "medical", records_officer=False)
        self.patient = make_patient("pat1")
        self.request = services.create_request(
            self.patient, "correction", "Wrong phone", "My phone number is wrong.")

    def login(self, username):
        self.client.logout()
        self.assertTrue(self.client.login(username=username, password=PW))

    def test_officer_can_list_open_answer_and_it_is_audited(self):
        self.login("officer")
        page = self.client.get(reverse("datarequests:manage"))
        self.assertEqual(page.status_code, 200)
        self.assertEqual([r.pk for r in page.context["requests"]], [self.request.pk])
        self.assertEqual(self.client.get(
            reverse("datarequests:detail", args=[self.request.pk])).status_code, 200)
        self.assertTrue(AuditLog.objects.filter(action="data_request_viewed").exists())
        response = self.client.post(reverse("datarequests:handle", args=[self.request.pk]),
                                    {"status": "resolved", "response": "Updated, thank you."})
        self.assertEqual(response.status_code, 302)
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, "resolved")
        self.assertEqual(self.request.handled_by, self.officer)

    def test_other_staff_cannot_even_if_administrative(self):
        for name in ("clerk", "doc"):
            self.login(name)
            self.assertEqual(self.client.get(reverse("datarequests:manage")).status_code, 403, name)
            self.assertEqual(self.client.get(
                reverse("datarequests:detail", args=[self.request.pk])).status_code, 404, name)
            self.assertEqual(self.client.post(
                reverse("datarequests:handle", args=[self.request.pk]),
                {"status": "resolved", "response": "x"}).status_code, 403, name)
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, "open")

    def test_officer_gets_no_other_admin_powers(self):
        self.login("officer")
        for name in ("core:audit_list", "accounts:staff_list"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)

    def test_officer_dashboard_shows_the_waiting_count_and_menu_link(self):
        self.login("officer")
        page = self.client.get(reverse("accounts:dashboard"))
        self.assertEqual(page.context["dash"]["open_requests"], 1)
        self.assertContains(page, reverse("datarequests:manage"))
        self.login("clerk")
        page = self.client.get(reverse("accounts:dashboard"))
        self.assertNotContains(page, reverse("datarequests:manage"))
