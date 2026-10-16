from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from cases.tests import make_user
from core.models import AuditLog
from notifications.models import Notification

from . import services
from .models import LabResult
from .tests import LabBase


class AmendServiceTests(LabBase):
    def test_amend_keeps_the_old_value_and_updates_the_result(self):
        result = self.released_result()  # value "Positive"
        services.amend_result(result, "Negative", "repeat sample", "Sample was mislabelled", self.doc)
        result.refresh_from_db()
        self.assertEqual((result.value, result.result_notes, result.status), ("Negative", "repeat sample", "released"))
        self.assertIsNotNone(result.amended_at)
        a = result.amendments.get()
        self.assertEqual((a.old_value, a.new_value, a.reason, a.amended_by), ("Positive", "Negative", "Sample was mislabelled", self.doc))

    def test_two_amendments_keep_the_whole_history(self):
        result = self.released_result()
        services.amend_result(result, "Negative", "", "First correction", self.doc)
        services.amend_result(result, "Weak positive", "", "Second correction", self.head)
        values = [(a.old_value, a.new_value) for a in result.amendments.all()]
        self.assertEqual(values, [("Positive", "Negative"), ("Negative", "Weak positive")])

    def test_only_a_released_result_can_be_amended(self):
        result = services.order_tests(self.case, [self.test_a], self.doc)[0]
        with self.assertRaises(ValidationError):
            services.amend_result(result, "x", "", "why", self.doc)
        services.enter_result(result, "Positive", "", self.tech)
        with self.assertRaises(ValidationError):
            services.amend_result(result, "x", "", "why", self.doc)

    def test_empty_value_empty_reason_and_no_change_are_refused(self):
        result = self.released_result()
        for args in (("", "", "why"), ("Negative", "", "  "), ("Positive", "", "why")):
            with self.assertRaises(ValidationError, msg=args):
                services.amend_result(result, args[0], args[1], args[2], self.doc)
        self.assertEqual(result.amendments.count(), 0)
        result.refresh_from_db()
        self.assertIsNone(result.amended_at)

    def test_who_may_amend(self):
        boss = make_user("boss")
        boss.role = "sub_admin"
        boss.save()
        for user in (self.tech, self.other_doc, self.cleaner, self.p1.user, boss):
            result = self.released_result()
            with self.assertRaises(PermissionDenied, msg=user.username):
                services.amend_result(result, "Negative", "", "why", user)
            self.assertEqual(result.amendments.count(), 0)
        for user in (self.doc, self.head, self.senior_tech):
            result = self.released_result()
            services.amend_result(result, "Negative", "", "why", user)
            self.assertEqual(result.amendments.count(), 1, user.username)

    def test_patient_is_notified_and_the_doctor_only_when_someone_else_amends(self):
        result = self.released_result()
        services.amend_result(result, "Negative", "", "why", self.doc)
        self.assertEqual(Notification.objects.filter(recipient=self.p1.user, kind="lab_amended").count(), 1)
        self.assertFalse(Notification.objects.filter(recipient=self.doc).exists())
        services.amend_result(result, "Weak", "", "again", self.senior_tech)
        self.assertEqual(Notification.objects.filter(recipient=self.p1.user, kind="lab_amended").count(), 2)
        self.assertEqual(Notification.objects.filter(recipient=self.doc, kind="lab_amended").count(), 1)

    def test_notifications_and_audit_hold_no_values_or_reason(self):
        result = self.released_result()
        services.amend_result(result, "VALUE-NEW-9", "NOTE-NEW", "REASON-TEXT", self.senior_tech)
        for n in Notification.objects.all():
            for text in (n.title, n.body):
                for secret in ("Positive", "VALUE-NEW-9", "NOTE-NEW", "REASON-TEXT", result.test.name):
                    self.assertNotIn(secret, text)
            self.assertEqual(n.url, reverse("laboratory:result", args=[result.pk]))
        entry = AuditLog.objects.get(action="lab_result_amended")
        for secret in ("Positive", "VALUE-NEW-9", "NOTE-NEW", "REASON-TEXT"):
            self.assertNotIn(secret, entry.detail)

    def test_a_failed_amendment_sends_nothing(self):
        result = self.released_result()
        with self.assertRaises(ValidationError):
            services.amend_result(result, "Positive", "", "no change", self.doc)
        self.assertEqual(Notification.objects.count(), 0)


class AmendViewTests(LabBase):
    def amend(self, result, value="Negative", notes="", reason="Sample mislabelled"):
        return self.client.post(reverse("laboratory:result_amend", args=[result.pk]),
                                {"value": value, "notes": notes, "reason": reason})

    def test_doctor_amends_through_the_page(self):
        result = self.released_result()
        self.login("doc")
        self.assertEqual(self.amend(result).status_code, 302)
        result.refresh_from_db()
        self.assertEqual(result.value, "Negative")
        page = self.client.get(reverse("laboratory:result", args=[result.pk]))
        self.assertContains(page, "Amendment history")
        self.assertContains(page, "Sample mislabelled")

    def test_missing_reason_changes_nothing(self):
        result = self.released_result()
        self.login("doc")
        self.assertEqual(self.amend(result, reason="").status_code, 302)
        result.refresh_from_db()
        self.assertEqual(result.value, "Positive")
        self.assertEqual(result.amendments.count(), 0)

    def test_others_cannot_amend(self):
        result = self.released_result()
        self.login("tech")
        self.assertEqual(self.amend(result).status_code, 403)
        self.login("pat1")
        self.assertEqual(self.amend(result).status_code, 403)
        self.login("otherdoc")
        self.assertEqual(self.amend(result).status_code, 404)
        self.login("pat2")
        self.assertEqual(self.amend(result).status_code, 404)
        result.refresh_from_db()
        self.assertEqual(result.value, "Positive")

    def test_amend_form_shown_only_to_those_who_may_amend(self):
        result = self.released_result()
        url = reverse("laboratory:result", args=[result.pk])
        for username, shown in (("doc", True), ("head", True), ("seniortech", True), ("tech", False), ("pat1", False)):
            self.login(username)
            self.assertEqual("Amend this result" in self.client.get(url).content.decode(), shown, username)

    def test_amend_form_not_offered_before_release(self):
        result = services.order_tests(self.case, [self.test_a], self.doc)[0]
        services.enter_result(result, "Positive", "", self.tech)
        self.login("doc")
        self.assertNotContains(self.client.get(reverse("laboratory:result", args=[result.pk])), "Amend this result")

    def test_patient_sees_the_amendment_and_follows_the_notification(self):
        result = self.released_result()
        services.amend_result(result, "Negative", "", "Sample mislabelled", self.senior_tech)
        self.login("pat1")
        page = self.client.get(reverse("laboratory:result", args=[result.pk]))
        self.assertContains(page, "This result was amended")
        self.assertContains(page, "Before: Positive")
        self.assertContains(page, "Sample mislabelled")
        self.assertNotContains(page, "seniortech")  # who amended is staff-only
        self.assertContains(self.client.get(reverse("laboratory:mine")), "(amended")
        note = Notification.objects.get(recipient=self.p1.user)
        self.assertEqual(self.client.get(note.url).status_code, 200)

    def test_other_patient_still_cannot_see_an_amended_result(self):
        result = self.released_result()
        services.amend_result(result, "Negative", "", "why", self.doc)
        self.login("pat2")
        self.assertEqual(self.client.get(reverse("laboratory:result", args=[result.pk])).status_code, 404)

    def test_print_shows_the_corrected_value_and_a_note_but_not_the_old_value(self):
        result = self.released_result()
        services.amend_result(result, "Negative", "", "why", self.doc)
        self.login("pat1")
        page = self.client.get(reverse("laboratory:print", args=[result.pk]))
        self.assertContains(page, "Negative")
        self.assertContains(page, "corrected on")
        self.assertNotContains(page, "Positive")
