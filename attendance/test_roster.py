from datetime import time, timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from cases.tests import PW, make_user
from departments.models import Department

from . import roster_services, services
from .models import AttendanceRecord, RosterEntry, ShiftType
from .tests import staff

FAST = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


@FAST
class RosterBase(TestCase):
    def setUp(self):
        self.surgery = Department.objects.create(name="Surgery")
        self.physio = Department.objects.create(name="Physio")
        self.head = staff("head", "department_head", self.surgery)
        self.surgery.head = self.head
        self.surgery.save()
        self.doc = staff("doc", "doctor", self.surgery)
        self.physio_doc = staff("physiodoc", "doctor", self.physio)
        self.cleaner = staff("cleaner", "staff", None, category="support")
        self.boss = make_user("boss")
        self.boss.role = "main_admin"
        self.boss.save()
        self.shift = ShiftType.objects.create(
            name="Morning", start_time=time(7, 0), end_time=time(15, 0))
        self.today = timezone.localdate()

    def login(self, username):
        self.client.logout()
        self.assertTrue(self.client.login(username=username, password=PW))


class ServiceTests(RosterBase):
    def test_head_plans_a_range_and_duplicates_are_skipped(self):
        end = self.today + timedelta(days=2)
        self.assertEqual(roster_services.assign_shift(
            self.head, [self.doc], self.shift, self.today, end), 3)
        self.assertEqual(roster_services.assign_shift(
            self.head, [self.doc], self.shift, self.today, end), 0)
        self.assertEqual(RosterEntry.objects.filter(user=self.doc).count(), 3)

    def test_head_cannot_plan_another_departments_staff(self):
        with self.assertRaises(PermissionDenied):
            roster_services.assign_shift(
                self.head, [self.physio_doc], self.shift, self.today, self.today)
        self.assertEqual(RosterEntry.objects.count(), 0)

    def test_admin_can_plan_anyone(self):
        roster_services.assign_shift(
            self.boss, [self.physio_doc, self.cleaner], self.shift, self.today, self.today)
        self.assertEqual(RosterEntry.objects.count(), 2)

    def test_bad_dates_and_inactive_shift_are_rejected(self):
        yesterday = self.today - timedelta(days=1)
        for args in (
            ([self.doc], self.shift, yesterday, self.today),
            ([self.doc], self.shift, self.today, yesterday),
            ([self.doc], self.shift, self.today, self.today + timedelta(days=40)),
            ([], self.shift, self.today, self.today),
        ):
            with self.assertRaises(ValidationError):
                roster_services.assign_shift(self.head, *args)
        self.shift.is_active = False
        self.shift.save()
        with self.assertRaises(ValidationError):
            roster_services.assign_shift(self.head, [self.doc], self.shift, self.today, self.today)

    def test_remove_future_entries_only_and_only_for_your_team(self):
        future = RosterEntry.objects.create(user=self.doc, date=self.today, shift=self.shift)
        past = RosterEntry.objects.create(
            user=self.doc, date=self.today - timedelta(days=1), shift=self.shift)
        other = RosterEntry.objects.create(user=self.physio_doc, date=self.today, shift=self.shift)
        with self.assertRaises(ValidationError):
            roster_services.remove_entry(self.head, past)
        with self.assertRaises(PermissionDenied):
            roster_services.remove_entry(self.head, other)
        roster_services.remove_entry(self.head, future)
        self.assertFalse(RosterEntry.objects.filter(pk=future.pk).exists())


class AttendanceComparisonTests(RosterBase):
    def record_at(self, user, minutes_after_start):
        start = roster_services.shift_start(self.today, self.shift)
        return AttendanceRecord.objects.create(
            user=user, work_date=self.today, clock_in=start + timedelta(minutes=minutes_after_start),
            source="self", recorded_by=user)

    def test_lateness_uses_the_grace_period(self):
        entry = RosterEntry.objects.create(user=self.doc, date=self.today, shift=self.shift)
        label, late = roster_services.evaluate(self.record_at(self.doc, 10), [entry])
        self.assertEqual(late, 0)
        self.assertIn("Morning", label)
        _, late = roster_services.evaluate(self.record_at(self.doc, 45), [entry])
        self.assertEqual(late, 30)

    def test_no_planned_shift_means_nothing_to_compare(self):
        self.assertEqual(roster_services.evaluate(self.record_at(self.doc, 60), []), ("", 0))

    def test_planned_but_not_clocked_in_list(self):
        if timezone.localtime().time() < time(0, 20):
            self.skipTest("Too close to midnight for this check")
        early = ShiftType.objects.create(name="Early", start_time=time(0, 1), end_time=time(6, 0))
        RosterEntry.objects.create(user=self.doc, date=self.today, shift=early)
        self.assertEqual([e.user for e in roster_services.missing_today(self.head)], [self.doc])
        services.clock_in(self.doc)
        self.assertEqual(roster_services.missing_today(self.head), [])


class ViewTests(RosterBase):
    def post_data(self, **extra):
        data = {"staff": [self.doc.pk], "shift": self.shift.pk,
                "date_from": self.today.isoformat(),
                "date_to": (self.today + timedelta(days=1)).isoformat(),
                "building": "", "note": ""}
        data.update(extra)
        return data

    def test_head_plans_through_the_page(self):
        self.login("head")
        self.assertEqual(self.client.get(reverse("attendance:roster")).status_code, 200)
        response = self.client.post(reverse("attendance:roster_assign"), self.post_data())
        self.assertEqual(response.status_code, 302)
        self.assertEqual(RosterEntry.objects.filter(user=self.doc).count(), 2)

    def test_head_cannot_pick_staff_outside_the_team(self):
        self.login("head")
        self.client.post(reverse("attendance:roster_assign"),
                         self.post_data(staff=[self.physio_doc.pk]))
        self.assertEqual(RosterEntry.objects.count(), 0)

    def test_ordinary_staff_cannot_manage_but_can_see_their_own_roster(self):
        RosterEntry.objects.create(user=self.cleaner, date=self.today, shift=self.shift)
        self.login("cleaner")
        self.assertEqual(self.client.get(reverse("attendance:roster")).status_code, 403)
        self.assertEqual(self.client.post(reverse("attendance:roster_assign"),
                                          self.post_data()).status_code, 403)
        response = self.client.get(reverse("attendance:roster_mine"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["entries"]), 1)

    def test_remove_entry_view_scope(self):
        mine = RosterEntry.objects.create(user=self.doc, date=self.today, shift=self.shift)
        other = RosterEntry.objects.create(user=self.physio_doc, date=self.today, shift=self.shift)
        self.login("head")
        self.assertEqual(self.client.post(reverse("attendance:roster_remove", args=[other.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("attendance:roster_remove", args=[mine.pk])).status_code, 302)
        self.assertFalse(RosterEntry.objects.filter(pk=mine.pk).exists())

    def test_shift_types_are_for_admins_only(self):
        self.login("head")
        self.assertEqual(self.client.get(reverse("attendance:shifts")).status_code, 403)
        self.login("boss")
        response = self.client.post(reverse("attendance:shift_create"), {
            "name": "Night", "start_time": "19:00", "end_time": "07:00", "is_active": "on"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(ShiftType.objects.get(name="Night").is_overnight)

    def test_planned_shift_shows_on_the_dashboard_panel_and_team_page(self):
        RosterEntry.objects.create(user=self.doc, date=self.today, shift=self.shift)
        services.clock_in(self.doc)
        self.login("doc")
        dash = self.client.get(reverse("accounts:dashboard")).context["dash"]
        self.assertEqual(len(dash["attendance"]["shifts_today"]), 1)
        self.login("head")
        response = self.client.get(reverse("attendance:team"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(any(r.scheduled for r in response.context["records"]))
