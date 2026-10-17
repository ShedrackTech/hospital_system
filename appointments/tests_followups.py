"""Appointment follow-ups: notifications, reminders, the dashboard tile and linking a case."""
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from cases.models import Case
from core.models import AuditLog
from notifications.models import Notification

from . import services
from . import tests as base
from .models import Appointment

S = Appointment.Status


def make_case(patient, doctor, dept, status="assigned", complaint="Private complaint text"):
    return Case.objects.create(patient=patient, complaint=complaint, department=dept,
                               assigned_to=doctor, status=status)


@base.FAST
class NotificationTests(base.Base):
    book_url = reverse("appointments:book")

    def pick(self, reason="Cough"):
        slot = services.available_slots(self.doctor, self.monday)[0].start.isoformat()
        return {"doctor": self.doctor.pk, "date": self.monday.isoformat(), "slot": slot, "reason": reason}

    def test_patient_booking_notifies_the_doctor_only(self):
        self.client.force_login(self.patient.user)
        self.client.post(self.book_url, self.pick("SECRET-REASON"))
        appt = Appointment.objects.get()
        note = Notification.objects.get(recipient=self.doctor, kind="appointment_booked")
        self.assertEqual(note.url, reverse("appointments:detail", args=[appt.pk]))
        self.assertFalse(Notification.objects.filter(recipient=self.patient.user).exists())
        self.assertNotIn("SECRET-REASON", note.title + note.body)

    def test_front_desk_booking_notifies_patient_and_doctor(self):
        self.client.force_login(self.front)
        data = self.pick("SECRET-REASON")
        data["patient"] = self.patient.user.login_id
        self.client.post(self.book_url, data)
        for user in (self.patient.user, self.doctor):
            note = Notification.objects.get(recipient=user, kind="appointment_booked")
            self.assertNotIn("SECRET-REASON", note.title + note.body)
        self.assertFalse(Notification.objects.filter(recipient=self.front).exists())

    def test_a_failing_notification_does_not_undo_the_booking(self):
        self.client.force_login(self.patient.user)
        with mock.patch("appointments.notices.notifications.notify", side_effect=RuntimeError("boom")):
            with self.assertLogs("appointments.notices", level="ERROR"):
                resp = self.client.post(self.book_url, self.pick())
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Appointment.objects.count(), 1)

    def test_patient_cancelling_notifies_the_doctor_only(self):
        appt = base.make_appt(self.patient, self.doctor, base.at(self.monday, 9))
        self.client.force_login(self.patient.user)
        self.client.post(reverse("appointments:cancel", args=[appt.pk]), {"reason": ""})
        self.assertTrue(Notification.objects.filter(recipient=self.doctor, kind="appointment_cancelled").exists())
        self.assertFalse(Notification.objects.filter(recipient=self.patient.user).exists())

    def test_staff_cancelling_notifies_the_patient_without_the_reason(self):
        appt = base.make_appt(self.patient, self.doctor, base.at(self.monday, 9))
        self.client.force_login(self.front)
        self.client.post(reverse("appointments:cancel", args=[appt.pk]), {"reason": "SECRET-CANCEL-REASON"})
        note = Notification.objects.get(recipient=self.patient.user, kind="appointment_cancelled")
        self.assertNotIn("SECRET-CANCEL-REASON", note.title + note.body)
        self.assertTrue(Notification.objects.filter(recipient=self.doctor, kind="appointment_cancelled").exists())

    def test_the_doctor_cancelling_is_not_notified_of_their_own_action(self):
        appt = base.make_appt(self.patient, self.doctor, base.at(self.monday, 9))
        self.client.force_login(self.doctor)
        self.client.post(reverse("appointments:cancel", args=[appt.pk]), {"reason": "Emergency"})
        self.assertTrue(Notification.objects.filter(recipient=self.patient.user).exists())
        self.assertFalse(Notification.objects.filter(recipient=self.doctor).exists())

    def test_a_refused_cancellation_sends_nothing(self):
        appt = base.make_appt(self.patient, self.doctor, base.at(self.monday, 9))
        self.client.force_login(self.front)
        self.client.post(reverse("appointments:cancel", args=[appt.pk]), {"reason": ""})  # staff need a reason
        self.assertEqual(Notification.objects.count(), 0)

    def test_the_patient_can_open_the_notification_link(self):
        appt = base.make_appt(self.patient, self.doctor, base.at(self.monday, 9))
        self.client.force_login(self.front)
        self.client.post(reverse("appointments:cancel", args=[appt.pk]), {"reason": "Doctor on leave"})
        note = Notification.objects.get(recipient=self.patient.user)
        self.client.force_login(self.patient.user)
        self.assertEqual(self.client.get(note.url).status_code, 200)


@base.FAST
class ReminderTests(base.Base):
    def run_command(self):
        out = StringIO()
        call_command("send_appointment_reminders", stdout=out)
        return out.getvalue()

    def appt(self, hours, status=S.SCHEDULED):
        return base.make_appt(self.patient, self.doctor, timezone.now() + timedelta(hours=hours), status=status)

    def test_only_appointments_inside_the_window_are_reminded(self):
        near = self.appt(20)
        self.appt(48)
        self.appt(-3)
        self.assertIn("Reminders sent: 1", self.run_command())
        note = Notification.objects.get()
        self.assertEqual((note.recipient, note.kind), (self.patient.user, "appointment_reminder"))
        self.assertEqual(note.url, reverse("appointments:detail", args=[near.pk]))
        near.refresh_from_db()
        self.assertIsNotNone(near.reminder_sent_at)

    def test_each_appointment_is_reminded_once(self):
        self.appt(20)
        self.run_command()
        self.assertIn("Reminders sent: 0", self.run_command())
        self.assertEqual(Notification.objects.count(), 1)

    def test_cancelled_appointments_get_no_reminder(self):
        self.appt(20, status=S.CANCELLED)
        self.assertIn("Reminders sent: 0", self.run_command())

    def test_the_reminder_does_not_contain_the_reason(self):
        base.make_appt(self.patient, self.doctor, timezone.now() + timedelta(hours=5), reason="SECRET-REASON")
        self.run_command()
        note = Notification.objects.get()
        self.assertNotIn("SECRET-REASON", note.title + note.body)

    def test_inactive_patients_are_skipped_quietly(self):
        self.appt(20)
        self.patient.user.is_active = False
        self.patient.user.save()
        self.run_command()
        self.assertEqual(Notification.objects.count(), 0)


@base.FAST
class DashboardTileTests(base.Base):
    url = reverse("accounts:dashboard")

    def test_patient_sees_the_next_appointment_and_not_anothers(self):
        base.make_appt(self.patient, self.doctor, base.at(self.monday, 9))
        self.client.force_login(self.patient.user)
        self.assertContains(self.client.get(self.url), "Next appointment")
        self.client.force_login(self.other_patient.user)
        page = self.client.get(self.url)
        self.assertContains(page, "You have no upcoming appointments")
        self.assertNotContains(page, "Next appointment:")

    def test_doctor_sees_counts_of_their_own_appointments(self):
        base.make_appt(self.patient, self.doctor, base.at(self.monday, 9))
        self.client.force_login(self.doctor)
        page = self.client.get(self.url)
        self.assertContains(page, "Upcoming appointments")
        self.assertContains(page, "Appointments today")

    def test_front_desk_sees_counts_without_reasons(self):
        base.make_appt(self.patient, self.doctor, base.at(self.monday, 9), reason="SECRET-REASON")
        self.client.force_login(self.front)
        page = self.client.get(self.url)
        self.assertContains(page, "Upcoming appointments")
        self.assertNotContains(page, "SECRET-REASON")

    def test_support_staff_see_no_appointment_box(self):
        self.client.force_login(self.support)
        page = self.client.get(self.url)
        self.assertNotContains(page, "Appointments today")
        self.assertNotContains(page, "Next appointment")


@base.FAST
class NavigationTests(base.Base):
    link = f'href="{reverse("appointments:home")}"'

    def test_who_gets_the_appointments_link(self):
        for user, shown in ((self.patient.user, True), (self.doctor, True), (self.front, True), (self.support, False)):
            self.client.force_login(user)
            page = self.client.get(reverse("accounts:dashboard"))
            self.assertEqual(self.link in page.content.decode(), shown, user.username)


@base.FAST
class CaseLinkTests(base.Base):
    def setUp(self):
        super().setUp()
        self.appt = base.make_appt(self.patient, self.doctor, base.at(self.monday, 9))
        self.case = make_case(self.patient, self.doctor, self.dept)
        self.detail = reverse("appointments:detail", args=[self.appt.pk])

    def link(self, user, case=None):
        self.client.force_login(user)
        return self.client.post(reverse("appointments:link_case", args=[self.appt.pk]),
                                {"case": (case or self.case).pk})

    def test_doctor_links_their_own_case_and_it_is_audited_without_the_complaint(self):
        self.assertEqual(self.link(self.doctor).status_code, 302)
        self.appt.refresh_from_db()
        self.assertEqual((self.appt.case, self.appt.case_linked_by), (self.case, self.doctor))
        entry = AuditLog.objects.get(action="appointment_case_linked")
        self.assertIn(f"Case #{self.case.pk}", entry.detail)
        self.assertNotIn("Private complaint", entry.detail)

    def test_the_head_can_link_a_case_of_the_department(self):
        head = base.make_doctor(self.dept, role="senior_doctor")
        self.dept.head = head
        self.dept.save()
        colleague = base.make_doctor(self.dept)
        case = make_case(self.patient, colleague, self.dept)
        self.link(head, case)
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.case, case)

    def test_cases_that_do_not_qualify_are_refused(self):
        other_doc = base.make_doctor(base.make_department())
        bad = [
            make_case(self.patient, other_doc, self.dept),                          # assigned to someone else
            make_case(self.patient, self.doctor, self.dept, status="completed"),   # finished
            make_case(self.other_patient, self.doctor, self.dept),                 # another patient's case
        ]
        pending = Case.objects.create(patient=self.patient, complaint="x", department=self.dept)  # not assigned
        bad.append(pending)
        for case in bad:
            self.link(self.doctor, case)
        self.appt.refresh_from_db()
        self.assertIsNone(self.appt.case)

    def test_others_cannot_link(self):
        for user in (self.front, self.admin, self.patient.user):
            self.assertEqual(self.link(user).status_code, 403, user.username)
        self.assertEqual(self.link(self.other_patient.user).status_code, 404)
        stranger = base.make_doctor(base.make_department())
        self.assertEqual(self.link(stranger).status_code, 404)
        self.appt.refresh_from_db()
        self.assertIsNone(self.appt.case)

    def test_a_cancelled_appointment_cannot_be_linked(self):
        Appointment.objects.filter(pk=self.appt.pk).update(status=S.CANCELLED)
        self.link(self.doctor)
        self.appt.refresh_from_db()
        self.assertIsNone(self.appt.case)

    def test_linking_the_same_case_twice_changes_nothing_more(self):
        self.link(self.doctor)
        self.link(self.doctor)
        self.assertEqual(AuditLog.objects.filter(action="appointment_case_linked").count(), 1)

    def test_unlink(self):
        self.link(self.doctor)
        self.client.force_login(self.doctor)
        self.client.post(reverse("appointments:unlink_case", args=[self.appt.pk]))
        self.appt.refresh_from_db()
        self.assertIsNone(self.appt.case)
        self.assertTrue(AuditLog.objects.filter(action="appointment_case_unlinked").exists())

    def test_unlink_is_for_the_doctor_or_head_only(self):
        self.link(self.doctor)
        self.client.force_login(self.front)
        self.assertEqual(self.client.post(reverse("appointments:unlink_case", args=[self.appt.pk])).status_code, 403)
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.case, self.case)

    def test_unlink_with_nothing_linked_is_a_quiet_error(self):
        self.client.force_login(self.doctor)
        resp = self.client.post(reverse("appointments:unlink_case", args=[self.appt.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(AuditLog.objects.filter(action="appointment_case_unlinked").exists())

    def test_the_detail_page_offers_the_form_to_the_doctor_only(self):
        self.client.force_login(self.doctor)
        self.assertContains(self.client.get(self.detail), "Link this case")
        for user in (self.front, self.patient.user):
            self.client.force_login(user)
            self.assertNotContains(self.client.get(self.detail), "Link this case")

    def test_the_linked_case_shows_to_everyone_who_can_see_the_appointment(self):
        self.link(self.doctor)
        for user in (self.doctor, self.front, self.patient.user):
            self.client.force_login(user)
            self.assertContains(self.client.get(self.detail), f"Case #{self.case.pk}", msg_prefix=user.username)

    def test_the_form_never_shows_the_complaint(self):
        self.client.force_login(self.doctor)
        self.assertNotContains(self.client.get(self.detail), "Private complaint text")
