from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from cases.tests import PW, make_patient, make_user
from core.models import AuditLog
from departments.models import Department, StaffProfile

from . import services
from .models import AttendanceCorrection, AttendanceRecord

FAST = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


def staff(username, role, dept, category="medical", officer=False):
    user = make_user(username)
    user.role = role
    user.save()
    StaffProfile.objects.create(user=user, category=category, job_title="Staff",
                                department=dept, grade="junior", attendance_officer=officer)
    return user


@FAST
class AttendanceBase(TestCase):
    def setUp(self):
        self.surgery = Department.objects.create(name="Surgery")
        self.physio = Department.objects.create(name="Physio")
        self.head = staff("head", "department_head", self.surgery)
        self.surgery.head = self.head
        self.surgery.save()
        self.doc = staff("doc", "doctor", self.surgery)
        self.physio_doc = staff("physiodoc", "doctor", self.physio)
        self.gateman = staff("gateman", "staff", None, category="support", officer=True)
        self.cleaner = staff("cleaner", "staff", None, category="support")
        self.boss = make_user("boss")
        self.boss.role = "main_admin"
        self.boss.save()
        self.patient = make_patient("pat1")

    def login(self, username):
        self.client.logout()
        self.assertTrue(self.client.login(username=username, password=PW))


class ServiceTests(AttendanceBase):
    def test_self_clock_in_and_out(self):
        record = services.clock_in(self.doc)
        self.assertEqual(record.source, "self")
        self.assertFalse(record.is_confirmed)
        services.clock_out(self.doc)
        record.refresh_from_db()
        self.assertIsNotNone(record.clock_out)

    def test_cannot_clock_in_twice_or_out_without_in(self):
        with self.assertRaises(ValidationError):
            services.clock_out(self.doc)
        services.clock_in(self.doc)
        with self.assertRaises(ValidationError):
            services.clock_in(self.doc)

    def test_patients_cannot_clock_in(self):
        with self.assertRaises(ValidationError):
            services.clock_in(self.patient.user)

    def test_officer_records_arrival_confirmed_and_not_themselves(self):
        record = services.record_arrival(self.gateman, self.cleaner)
        self.assertEqual(record.source, "officer")
        self.assertTrue(record.is_confirmed)
        with self.assertRaises(ValidationError):
            services.record_arrival(self.gateman, self.gateman)
        with self.assertRaises(PermissionDenied):
            services.record_arrival(self.doc, self.cleaner)

    def test_confirm_rules(self):
        record = services.clock_in(self.doc)
        with self.assertRaises(PermissionDenied):
            services.confirm_record(self.doc, record)          # not your own
        with self.assertRaises(PermissionDenied):
            services.confirm_record(self.physio_doc, record)   # not your department
        services.confirm_record(self.head, record)             # department head
        record.refresh_from_db()
        self.assertEqual(record.confirmed_by, self.head)
        with self.assertRaises(ValidationError):
            services.confirm_record(self.head, record)         # already confirmed

    def test_correction_keeps_old_values_needs_reason_and_is_audited(self):
        record = services.clock_in(self.doc)
        old_in = record.clock_in
        new_in = old_in - timedelta(hours=1)
        with self.assertRaises(ValidationError):
            services.correct_record(self.head, record, new_in, None, "  ")
        with self.assertRaises(PermissionDenied):
            services.correct_record(self.doc, record, new_in, None, "I was early")
        services.correct_record(self.head, record, new_in, old_in, "Forgot to clock in")
        record.refresh_from_db()
        correction = AttendanceCorrection.objects.get(record=record)
        self.assertEqual(correction.old_clock_in, old_in)
        self.assertEqual(record.clock_in, new_in)
        self.assertTrue(record.is_confirmed)
        self.assertTrue(AuditLog.objects.filter(action="attendance_corrected").exists())

    def test_correction_rejects_bad_times(self):
        record = services.clock_in(self.doc)
        later = timezone.now() + timedelta(hours=3)
        with self.assertRaises(ValidationError):
            services.correct_record(self.head, record, later, None, "future")
        with self.assertRaises(ValidationError):
            services.correct_record(self.head, record, record.clock_in,
                                    record.clock_in - timedelta(hours=1), "backwards")


class ViewTests(AttendanceBase):
    def test_staff_can_clock_in_and_out_from_pages(self):
        self.login("cleaner")
        self.assertEqual(self.client.post(reverse("attendance:clock_in")).status_code, 302)
        self.assertEqual(AttendanceRecord.objects.filter(user=self.cleaner).count(), 1)
        self.assertEqual(self.client.post(reverse("attendance:clock_out")).status_code, 302)
        self.assertIsNotNone(AttendanceRecord.objects.get(user=self.cleaner).clock_out)

    def test_patients_and_admins_without_a_profile_are_blocked(self):
        for name in ("pat1", "boss"):
            self.login(name)
            self.assertEqual(self.client.get(reverse("attendance:mine")).status_code, 403, name)

    def test_team_page_scope(self):
        mine = services.clock_in(self.doc)
        other = services.clock_in(self.physio_doc)
        self.login("head")
        ids = [r.pk for r in self.client.get(reverse("attendance:team")).context["records"]]
        self.assertIn(mine.pk, ids)
        self.assertNotIn(other.pk, ids)  # another department
        self.login("gateman")  # officer sees everyone
        ids = [r.pk for r in self.client.get(reverse("attendance:team")).context["records"]]
        self.assertTrue({mine.pk, other.pk} <= set(ids))

    def test_ordinary_staff_and_patients_cannot_open_the_team_page(self):
        for name in ("cleaner", "pat1"):
            self.login(name)
            self.assertEqual(self.client.get(reverse("attendance:team")).status_code, 403, name)

    def test_admins_see_all_attendance_even_without_a_staff_profile(self):
        record = services.clock_in(self.doc)
        self.login("boss")
        response = self.client.get(reverse("attendance:team"))
        self.assertEqual(response.status_code, 200)
        self.assertIn(record.pk, [r.pk for r in response.context["records"]])

    def test_head_confirms_team_member_and_stranger_gets_404(self):
        record = services.clock_in(self.doc)
        url = reverse("attendance:confirm", args=[record.pk])
        self.login("physiodoc")  # ordinary staff: no access to the team tools at all
        self.assertEqual(self.client.post(url).status_code, 403)
        self.login("doc")
        self.assertEqual(self.client.post(url).status_code, 403)  # cannot confirm own
        self.login("head")
        self.assertEqual(self.client.post(url).status_code, 302)
        record.refresh_from_db()
        self.assertTrue(record.is_confirmed)

    def test_officer_records_arrival_by_staff_id(self):
        self.login("gateman")
        response = self.client.post(reverse("attendance:officer_record"),
                                    {"staff_id": self.cleaner.login_id})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(AttendanceRecord.objects.filter(user=self.cleaner, source="officer").exists())
        self.login("doc")
        self.assertEqual(self.client.post(reverse("attendance:officer_record"),
                                          {"staff_id": self.cleaner.login_id}).status_code, 403)

    def test_correction_page_and_post(self):
        record = services.clock_in(self.doc)
        url = reverse("attendance:correct", args=[record.pk])
        self.login("doc")
        self.assertEqual(self.client.get(url).status_code, 403)
        self.login("head")
        self.assertEqual(self.client.get(url).status_code, 200)
        earlier = timezone.localtime(record.clock_in - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M")
        response = self.client.post(url, {"clock_in": earlier, "clock_out": "", "reason": "Late entry"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(AttendanceCorrection.objects.filter(record=record).count(), 1)

    def test_old_unconfirmed_records_are_flagged_for_review(self):
        yesterday = timezone.now() - timedelta(days=1)
        old = AttendanceRecord.objects.create(
            user=self.doc, work_date=timezone.localtime(yesterday).date(),
            clock_in=yesterday, clock_out=yesterday + timedelta(hours=8), source="self",
            recorded_by=self.doc,
        )
        self.login("head")
        response = self.client.get(reverse("attendance:team"), {"status": "flagged"})
        self.assertIn(old.pk, [r.pk for r in response.context["records"]])
        dash = self.client.get(reverse("accounts:dashboard")).context["dash"]
        self.assertEqual(dash["attendance"]["review_count"], 1)

    def test_pages_and_dashboard_panel_render(self):
        services.clock_in(self.doc)
        self.login("doc")
        self.assertEqual(self.client.get(reverse("attendance:mine")).status_code, 200)
        page = self.client.get(reverse("accounts:dashboard"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Clock out")
        self.login("cleaner")
        self.assertContains(self.client.get(reverse("accounts:dashboard")), "Clock in")
