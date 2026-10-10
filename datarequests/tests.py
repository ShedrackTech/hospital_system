from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from cases.tests import PW, make_patient, make_user
from core.models import AuditLog
from departments.models import StaffProfile

from . import services
from .models import DataRequest

FAST = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


def person(username, role, category=None):
    user = make_user(username)
    user.role = role
    user.save()
    if category:
        StaffProfile.objects.create(user=user, category=category, job_title="Staff",
                                    department=None, grade="junior")
    return user


@FAST
class DataRequestBase(TestCase):
    def setUp(self):
        self.p1 = make_patient("pat1")
        self.p2 = make_patient("pat2")
        self.boss = person("boss", "main_admin")
        self.sub = person("sub", "sub_admin")
        self.doc = person("doc", "doctor", "medical")

    def login(self, username):
        self.client.logout()
        self.assertTrue(self.client.login(username=username, password=PW))

    def make(self, patient=None, kind="correction"):
        return services.create_request(
            patient or self.p1, kind, "Wrong date of birth", "My date of birth is wrong.")


class ServiceTests(DataRequestBase):
    def test_create_is_open_and_audited_without_the_text(self):
        request = self.make()
        self.assertEqual(request.status, "open")
        entry = AuditLog.objects.get(action="data_request_created")
        self.assertEqual(entry.patient, self.p1)
        self.assertNotIn("date of birth", entry.detail.lower())

    def test_empty_fields_and_unknown_kind_are_rejected(self):
        with self.assertRaises(ValidationError):
            services.create_request(self.p1, "correction", " ", "x")
        with self.assertRaises(ValidationError):
            services.create_request(self.p1, "nonsense", "s", "d")

    def test_limit_on_open_requests(self):
        for _ in range(services.MAX_OPEN_REQUESTS):
            self.make()
        with self.assertRaises(ValidationError):
            self.make()
        self.make(self.p2)  # another patient is not affected

    def test_closing_needs_an_answer_and_closed_is_final(self):
        request = self.make()
        with self.assertRaises(ValidationError):
            services.update_request(self.boss, request, "resolved", "  ")
        services.update_request(self.boss, request, "in_review", "")
        done = services.update_request(self.boss, request, "resolved", "Corrected.")
        self.assertEqual(done.handled_by, self.boss)
        with self.assertRaises(ValidationError):
            services.update_request(self.boss, request, "declined", "Changed my mind")
        updates = AuditLog.objects.filter(action="data_request_updated")
        self.assertEqual(updates.count(), 2)
        self.assertNotIn("Corrected", " ".join(updates.values_list("detail", flat=True)))


class ViewTests(DataRequestBase):
    def test_patient_sends_and_sees_only_their_own_requests(self):
        self.login("pat1")
        response = self.client.post(reverse("datarequests:new"), {
            "kind": "access", "subject": "Copy please", "details": "I need my records."})
        self.assertEqual(response.status_code, 302)
        mine = self.client.get(reverse("datarequests:mine")).context["requests"]
        self.assertEqual(len(mine), 1)
        other = self.make(self.p2)
        self.assertEqual(self.client.get(reverse("datarequests:detail", args=[other.pk])).status_code, 404)

    def test_staff_and_admins_cannot_use_the_patient_pages(self):
        for name in ("doc", "boss"):
            self.login(name)
            self.assertEqual(self.client.get(reverse("datarequests:mine")).status_code, 403, name)
            self.assertEqual(self.client.get(reverse("datarequests:new")).status_code, 403, name)

    def test_only_admins_see_the_manage_list_and_handle(self):
        request = self.make()
        for name in ("pat1", "doc"):
            self.login(name)
            self.assertEqual(self.client.get(reverse("datarequests:manage")).status_code, 403, name)
            self.assertEqual(self.client.post(
                reverse("datarequests:handle", args=[request.pk]),
                {"status": "resolved", "response": "x"}).status_code, 403, name)
        self.login("sub")
        response = self.client.get(reverse("datarequests:manage"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([r.pk for r in response.context["requests"]], [request.pk])

    def test_doctor_cannot_open_a_request_and_admin_view_is_audited(self):
        request = self.make()
        url = reverse("datarequests:detail", args=[request.pk])
        self.login("doc")
        self.assertEqual(self.client.get(url).status_code, 404)
        self.login("boss")
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertTrue(AuditLog.objects.filter(action="data_request_viewed").exists())

    def test_admin_answers_and_the_patient_reads_the_answer(self):
        request = self.make(kind="deletion")
        self.login("boss")
        response = self.client.post(reverse("datarequests:handle", args=[request.pk]), {
            "status": "declined", "response": "Medical records must be kept for 10 years."})
        self.assertEqual(response.status_code, 302)
        self.login("pat1")
        page = self.client.get(reverse("datarequests:detail", args=[request.pk]))
        self.assertContains(page, "must be kept for 10 years")
        self.assertContains(page, "Declined")

    def test_closing_without_an_answer_changes_nothing(self):
        request = self.make()
        self.login("boss")
        self.client.post(reverse("datarequests:handle", args=[request.pk]),
                         {"status": "resolved", "response": ""})
        request.refresh_from_db()
        self.assertEqual(request.status, "open")

    def test_dashboard_shows_the_open_count_to_admins(self):
        self.make()
        self.make(self.p2)
        self.login("boss")
        dash = self.client.get(reverse("accounts:dashboard")).context["dash"]
        self.assertEqual(dash["open_requests"], 2)
        self.login("pat1")
        self.assertEqual(self.client.get(reverse("accounts:dashboard")).status_code, 200)
