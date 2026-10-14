import itertools
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import AuditLog
from departments.models import Department, StaffProfile
from patients.models import Patient

from . import rules, services
from .models import Appointment, DoctorAvailability

User = get_user_model()
FAST = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
PW = "Test-pass-12345"
_n = itertools.count(1)
S = Appointment.Status


# ---------- helpers (self-contained, so they do not depend on other apps' test code) ----------

def _fill_required(model, skip=()):
    """Fill any required plain field we do not know about, so tests survive model additions."""
    data, n = {}, next(_n)
    for f in model._meta.concrete_fields:
        if (f.primary_key or f.name in skip or f.null or f.blank or f.has_default() or f.is_relation
                or getattr(f, "auto_now", False) or getattr(f, "auto_now_add", False)):
            continue
        if f.choices:
            data[f.name] = f.choices[0][0]
        elif isinstance(f, models.DateTimeField):
            data[f.name] = timezone.now()
        elif isinstance(f, models.DateField):
            data[f.name] = date(1990, 1, 1)
        elif isinstance(f, models.DecimalField):
            data[f.name] = Decimal("1")
        elif isinstance(f, (models.IntegerField, models.FloatField)):
            data[f.name] = 1
        elif isinstance(f, models.BooleanField):
            data[f.name] = False
        else:
            data[f.name] = f"x{n}"
    return data


def make_user(role="patient", **extra):
    n = next(_n)
    return User.objects.create_user(
        username=f"user{n}", password=PW, role=role, first_name="Test", last_name=f"User{n}", **extra
    )


def make_department(**kw):
    n = next(_n)
    return Department.objects.create(name=f"Dept {n}", description="Test", **kw)


def make_doctor(dept, role="doctor"):
    u = make_user(role)
    StaffProfile.objects.create(user=u, category="medical", job_title="Doctor", department=dept, grade="junior")
    return u


def make_staff(category, role="staff", dept=None):
    u = make_user(role)
    StaffProfile.objects.create(user=u, category=category, job_title="Staff", department=dept, grade="junior")
    return u


def make_patient():
    u = make_user("patient")
    p = Patient.objects.filter(user=u).first() or Patient.objects.create(user=u, **_fill_required(Patient, {"user"}))
    return p


def make_admin():
    return make_user("sub_admin", is_staff=True)


def next_weekday(weekday, min_days=3):
    d = timezone.localdate() + timedelta(days=min_days)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d


def at(day, hh, mm=0):
    return timezone.make_aware(datetime.combine(day, time(hh, mm)))


def open_hours(doctor, weekday=0, start=(9, 0), end=(12, 0), minutes=30):
    return DoctorAvailability.objects.create(
        doctor=doctor, weekday=weekday, start_time=time(*start), end_time=time(*end), slot_minutes=minutes
    )


def make_appt(patient, doctor, starts_at, status=S.SCHEDULED, reason="Persistent headache"):
    return Appointment.objects.create(
        patient=patient, doctor=doctor, department=doctor.staff_profile.department,
        starts_at=starts_at, ends_at=starts_at + timedelta(minutes=30), reason=reason,
        status=status, booked_by=patient.user,
    )


class Base(TestCase):
    def setUp(self):
        self.dept = make_department()
        self.doctor = make_doctor(self.dept)
        self.monday = next_weekday(0)
        open_hours(self.doctor, weekday=0)
        self.patient = make_patient()
        self.other_patient = make_patient()
        self.front = make_staff("admin")
        self.admin = make_admin()
        self.support = make_staff("support")


# ---------- free times ----------

@FAST
class SlotTests(Base):
    def test_slots_follow_the_window(self):
        slots = services.available_slots(self.doctor, self.monday)
        self.assertEqual([timezone.localtime(s.start).strftime("%H:%M") for s in slots],
                         ["09:00", "09:30", "10:00", "10:30", "11:00", "11:30"])

    def test_booked_slot_disappears(self):
        make_appt(self.patient, self.doctor, at(self.monday, 9, 30))
        starts = [timezone.localtime(s.start).strftime("%H:%M") for s in services.available_slots(self.doctor, self.monday)]
        self.assertNotIn("09:30", starts)
        self.assertEqual(len(starts), 5)

    def test_cancelled_slot_is_free_again(self):
        make_appt(self.patient, self.doctor, at(self.monday, 9, 30), status=S.CANCELLED)
        self.assertEqual(len(services.available_slots(self.doctor, self.monday)), 6)

    def test_no_slots_on_a_day_without_hours(self):
        self.assertEqual(services.available_slots(self.doctor, self.monday + timedelta(days=1)), [])

    def test_no_slots_in_the_past_or_too_far_ahead(self):
        self.assertEqual(services.available_slots(self.doctor, timezone.localdate() - timedelta(days=7)), [])
        far = next_weekday(0, min_days=rules.MAX_DAYS_AHEAD + 1)
        self.assertEqual(services.available_slots(self.doctor, far), [])

    def test_doctor_in_general_department_takes_no_bookings(self):
        general = make_doctor(make_department(is_general=True))
        open_hours(general, weekday=0)
        self.assertEqual(services.available_slots(general, self.monday), [])

    def test_nurse_and_inactive_doctor_are_not_bookable(self):
        nurse = make_doctor(self.dept, role="nurse")
        open_hours(nurse, weekday=0)
        self.assertEqual(services.available_slots(nurse, self.monday), [])
        self.doctor.is_active = False
        self.doctor.save()
        self.assertEqual(services.available_slots(self.doctor, self.monday), [])


# ---------- booking ----------

@FAST
class BookingTests(Base):
    def book(self, who=None, patient=None, hh=9, mm=0, doctor=None, reason="Fever"):
        return services.book_appointment(
            patient or self.patient, doctor or self.doctor, at(self.monday, hh, mm), reason, who or self.patient.user
        )

    def test_patient_books_for_self_and_it_is_audited(self):
        appt = self.book()
        self.assertEqual(appt.status, S.SCHEDULED)
        self.assertEqual(appt.department, self.dept)
        self.assertEqual(appt.ends_at - appt.starts_at, timedelta(minutes=30))
        entry = AuditLog.objects.get(action="appointment_booked")
        self.assertNotIn("Fever", entry.detail)  # the reason is never copied into the log

    def test_front_desk_and_admin_can_book_for_a_patient(self):
        self.book(who=self.front)
        self.book(who=self.admin, patient=self.other_patient, hh=9, mm=30)
        self.assertEqual(Appointment.objects.count(), 2)

    def test_patient_cannot_book_for_someone_else(self):
        with self.assertRaises(PermissionDenied):
            self.book(who=self.patient.user, patient=self.other_patient)

    def test_support_staff_and_doctors_cannot_book(self):
        for who in (self.support, self.doctor):
            with self.assertRaises(PermissionDenied):
                self.book(who=who)

    def test_same_slot_cannot_be_booked_twice(self):
        self.book()
        with self.assertRaises(ValidationError):
            self.book(patient=self.other_patient, who=self.other_patient.user)

    def test_time_off_the_slot_grid_is_refused(self):
        with self.assertRaises(ValidationError):
            self.book(hh=9, mm=10)

    def test_time_outside_the_window_is_refused(self):
        with self.assertRaises(ValidationError):
            self.book(hh=14)

    def test_past_time_is_refused(self):
        with self.assertRaises(ValidationError):
            services.book_appointment(self.patient, self.doctor, at(timezone.localdate() - timedelta(days=7), 9),
                                      "x", self.patient.user)

    def test_reason_is_required(self):
        with self.assertRaises(ValidationError):
            self.book(reason="   ")

    def test_patient_limit_of_upcoming_appointments(self):
        for i in range(rules.MAX_UPCOMING_PER_PATIENT):
            self.book(hh=9 + i)
        with self.assertRaises(ValidationError):
            self.book(hh=9 + rules.MAX_UPCOMING_PER_PATIENT)

    def test_patient_cannot_be_in_two_places_at_once(self):
        other_doc = make_doctor(self.dept)
        open_hours(other_doc, weekday=0)
        self.book()
        with self.assertRaises(ValidationError):
            self.book(doctor=other_doc)

    def test_inactive_patient_cannot_be_booked(self):
        self.patient.user.is_active = False
        self.patient.user.save()
        with self.assertRaises(ValidationError):
            self.book(who=self.front)

    def test_database_refuses_a_double_booking_even_without_the_service(self):
        from django.db import IntegrityError, transaction
        make_appt(self.patient, self.doctor, at(self.monday, 9))
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_appt(self.other_patient, self.doctor, at(self.monday, 9))


# ---------- cancelling ----------

@FAST
class CancelTests(Base):
    def far(self):
        return make_appt(self.patient, self.doctor, at(self.monday, 9))

    def test_patient_can_cancel_their_own(self):
        a = services.cancel_appointment(self.far(), self.patient.user)
        self.assertEqual(a.status, S.CANCELLED)
        self.assertTrue(AuditLog.objects.filter(action="appointment_cancelled").exists())

    def test_patient_cannot_cancel_inside_the_cutoff(self):
        soon = make_appt(self.patient, self.doctor, timezone.now() + timedelta(hours=1))
        with self.assertRaises(ValidationError):
            services.cancel_appointment(soon, self.patient.user)

    def test_patient_cannot_cancel_someone_elses(self):
        with self.assertRaises(ValidationError):
            services.cancel_appointment(self.far(), self.other_patient.user)

    def test_staff_must_give_a_reason(self):
        a = self.far()
        with self.assertRaises(ValidationError):
            services.cancel_appointment(a, self.front, "")
        services.cancel_appointment(a, self.front, "Doctor is on leave")
        a.refresh_from_db()
        self.assertEqual(a.status, S.CANCELLED)
        self.assertNotIn("leave", AuditLog.objects.get(action="appointment_cancelled").detail)

    def test_doctor_and_admin_can_cancel_with_reason(self):
        services.cancel_appointment(self.far(), self.doctor, "Emergency")
        a2 = make_appt(self.patient, self.doctor, at(self.monday, 10))
        services.cancel_appointment(a2, self.admin, "Clash")

    def test_support_and_unrelated_doctor_cannot_cancel(self):
        stranger = make_doctor(make_department())
        a = self.far()
        for who in (self.support, stranger):
            with self.assertRaises(ValidationError):
                services.cancel_appointment(a, who, "no")

    def test_started_appointment_cannot_be_cancelled(self):
        past = make_appt(self.patient, self.doctor, timezone.now() - timedelta(minutes=10))
        with self.assertRaises(ValidationError):
            services.cancel_appointment(past, self.front, "late")

    def test_cancelling_twice_fails_and_frees_the_slot(self):
        a = self.far()
        services.cancel_appointment(a, self.patient.user)
        with self.assertRaises(ValidationError):
            services.cancel_appointment(a, self.patient.user)
        services.book_appointment(self.other_patient, self.doctor, at(self.monday, 9), "x", self.other_patient.user)


# ---------- recording the outcome ----------

@FAST
class CloseTests(Base):
    def started(self):
        return make_appt(self.patient, self.doctor, timezone.now() - timedelta(hours=1))

    def test_doctor_can_complete_and_mark_no_show(self):
        a = services.close_appointment(self.started(), S.COMPLETED, self.doctor)
        self.assertEqual(a.status, S.COMPLETED)
        self.assertTrue(AuditLog.objects.filter(action="appointment_completed").exists())

    def test_no_show(self):
        a = services.close_appointment(self.started(), S.NO_SHOW, self.doctor)
        self.assertEqual(a.status, S.NO_SHOW)
        self.assertTrue(AuditLog.objects.filter(action="appointment_no_show").exists())

    def test_department_head_can_close(self):
        head = make_doctor(self.dept, role="senior_doctor")
        self.dept.head = head
        self.dept.save()
        services.close_appointment(self.started(), S.COMPLETED, head)

    def test_not_before_the_start(self):
        future = make_appt(self.patient, self.doctor, timezone.now() + timedelta(days=1))
        with self.assertRaises(ValidationError):
            services.close_appointment(future, S.COMPLETED, self.doctor)

    def test_only_doctor_or_head_may_close(self):
        stranger = make_doctor(make_department())
        a = self.started()
        for who in (self.front, self.admin, self.support, stranger, self.patient.user):
            with self.assertRaises(ValidationError):
                services.close_appointment(a, S.COMPLETED, who)

    def test_cannot_close_twice_or_with_a_bad_status(self):
        a = services.close_appointment(self.started(), S.COMPLETED, self.doctor)
        with self.assertRaises(ValidationError):
            services.close_appointment(a, S.NO_SHOW, self.doctor)
        with self.assertRaises(ValidationError):
            services.close_appointment(self.started(), S.CANCELLED, self.doctor)


# ---------- who can open what ----------

@FAST
class AccessTests(Base):
    def setUp(self):
        super().setUp()
        self.appt = make_appt(self.patient, self.doctor, at(self.monday, 9), reason="Secret symptom text")
        self.url = reverse("appointments:detail", args=[self.appt.pk])

    def get(self, user):
        self.client.force_login(user)
        return self.client.get(self.url)

    def test_anonymous_is_sent_to_login(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_patient_sees_own_with_reason_and_not_audited(self):
        r = self.get(self.patient.user)
        self.assertContains(r, "Secret symptom text")
        self.assertFalse(AuditLog.objects.filter(action="appointment_viewed").exists())

    def test_other_patient_gets_404(self):
        self.assertEqual(self.get(self.other_patient.user).status_code, 404)

    def test_own_doctor_sees_reason_and_it_is_audited(self):
        r = self.get(self.doctor)
        self.assertContains(r, "Secret symptom text")
        self.assertTrue(AuditLog.objects.filter(action="appointment_viewed", patient=self.patient).exists())

    def test_unrelated_doctor_gets_404(self):
        self.assertEqual(self.get(make_doctor(make_department())).status_code, 404)

    def test_department_head_sees_department_appointments(self):
        head = make_doctor(self.dept, role="senior_doctor")
        self.dept.head = head
        self.dept.save()
        self.assertContains(self.get(head), "Secret symptom text")

    def test_front_desk_sees_the_booking_but_not_the_reason(self):
        r = self.get(self.front)
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "Secret symptom text")

    def test_admin_sees_reason(self):
        self.assertContains(self.get(self.admin), "Secret symptom text")

    def test_support_staff_and_nurse_get_404(self):
        self.assertEqual(self.get(self.support).status_code, 404)
        self.assertEqual(self.get(make_doctor(self.dept, role="nurse")).status_code, 404)

    def test_staff_list_is_closed_to_patients_and_support(self):
        for who in (self.patient.user, self.support):
            self.client.force_login(who)
            self.assertEqual(self.client.get(reverse("appointments:staff_list")).status_code, 403)

    def test_staff_list_shows_only_what_a_doctor_may_see(self):
        stranger = make_doctor(make_department())
        other = make_appt(self.other_patient, stranger, at(self.monday, 10))
        self.client.force_login(self.doctor)
        r = self.client.get(reverse("appointments:staff_list"))
        self.assertContains(r, reverse("appointments:detail", args=[self.appt.pk]))
        self.assertNotContains(r, reverse("appointments:detail", args=[other.pk]))
        self.assertTrue(AuditLog.objects.filter(action="appointment_list_viewed").exists())

    def test_my_appointments_page_is_only_for_patients(self):
        self.client.force_login(self.front)
        self.assertEqual(self.client.get(reverse("appointments:mine")).status_code, 403)
        self.client.force_login(self.patient.user)
        self.assertContains(self.client.get(reverse("appointments:mine")), "Open")

    def test_cancel_and_close_need_post(self):
        self.client.force_login(self.patient.user)
        self.assertEqual(self.client.get(reverse("appointments:cancel", args=[self.appt.pk])).status_code, 405)

    def test_cancel_through_the_page(self):
        self.client.force_login(self.patient.user)
        self.client.post(reverse("appointments:cancel", args=[self.appt.pk]), {"reason": ""})
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.status, S.CANCELLED)

    def test_other_patient_cannot_cancel_through_the_page(self):
        self.client.force_login(self.other_patient.user)
        r = self.client.post(reverse("appointments:cancel", args=[self.appt.pk]), {"reason": ""})
        self.assertEqual(r.status_code, 404)
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.status, S.SCHEDULED)


# ---------- the booking pages ----------

@FAST
class BookingPageTests(Base):
    url = reverse("appointments:book")

    def pick(self):
        slot = services.available_slots(self.doctor, self.monday)[0].start.isoformat()
        return {"doctor": self.doctor.pk, "date": self.monday.isoformat(), "slot": slot, "reason": "Cough"}

    def test_patient_sees_free_times(self):
        self.client.force_login(self.patient.user)
        r = self.client.get(self.url, {"doctor": self.doctor.pk, "date": self.monday.isoformat()})
        self.assertContains(r, "09:00 to 09:30")

    def test_patient_books_through_the_page(self):
        self.client.force_login(self.patient.user)
        r = self.client.post(self.url, self.pick())
        appt = Appointment.objects.get()
        self.assertRedirects(r, reverse("appointments:detail", args=[appt.pk]))
        self.assertEqual(appt.patient, self.patient)

    def test_a_patient_cannot_book_for_another_by_adding_a_card_number(self):
        self.client.force_login(self.patient.user)
        data = self.pick()
        data["patient"] = self.other_patient.user.login_id
        self.client.post(self.url, data)
        self.assertEqual(Appointment.objects.get().patient, self.patient)

    def test_front_desk_books_by_card_number(self):
        self.client.force_login(self.front)
        data = self.pick()
        data["patient"] = self.patient.user.login_id
        self.client.post(self.url, data)
        appt = Appointment.objects.get()
        self.assertEqual(appt.patient, self.patient)
        self.assertEqual(appt.booked_by, self.front)

    def test_front_desk_with_an_unknown_card_books_nothing(self):
        self.client.force_login(self.front)
        data = self.pick()
        data["patient"] = "PAT999999"
        r = self.client.post(self.url, data)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Appointment.objects.count(), 0)

    def test_taken_time_shows_an_error_and_books_nothing_new(self):
        data = self.pick()
        make_appt(self.other_patient, self.doctor, datetime.fromisoformat(data["slot"]))
        self.client.force_login(self.patient.user)
        r = self.client.post(self.url, data)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Appointment.objects.count(), 1)

    def test_support_staff_and_doctors_cannot_open_the_booking_page(self):
        for who in (self.support, self.doctor):
            self.client.force_login(who)
            self.assertEqual(self.client.get(self.url).status_code, 403)


# ---------- doctors' hours ----------

@FAST
class AvailabilityPageTests(Base):
    url = reverse("appointments:availability")

    def post(self, user, doctor, **extra):
        self.client.force_login(user)
        data = {"doctor": doctor.pk, "weekday": 1, "start_time": "13:00", "end_time": "15:00", "slot_minutes": 30}
        data.update(extra)
        return self.client.post(self.url, data)

    def test_doctor_adds_own_hours_and_it_is_audited(self):
        self.post(self.doctor, self.doctor)
        self.assertTrue(DoctorAvailability.objects.filter(doctor=self.doctor, weekday=1).exists())
        self.assertTrue(AuditLog.objects.filter(action="availability_added").exists())

    def test_doctor_cannot_change_another_doctors_hours(self):
        other = make_doctor(self.dept)
        self.post(self.doctor, other)
        self.assertFalse(DoctorAvailability.objects.filter(doctor=other).exists())
        self.assertTrue(DoctorAvailability.objects.filter(doctor=self.doctor, weekday=1).exists())

    def test_head_manages_own_department_only(self):
        head = make_doctor(self.dept, role="senior_doctor")
        self.dept.head = head
        self.dept.save()
        self.post(head, self.doctor)
        self.assertTrue(DoctorAvailability.objects.filter(doctor=self.doctor, weekday=1).exists())
        outsider = make_doctor(make_department())
        self.post(head, outsider)
        self.assertFalse(DoctorAvailability.objects.filter(doctor=outsider).exists())

    def test_admin_manages_anyone(self):
        self.post(self.admin, self.doctor)
        self.assertTrue(DoctorAvailability.objects.filter(doctor=self.doctor, weekday=1).exists())

    def test_nurse_front_desk_and_patient_are_refused(self):
        for who in (make_doctor(self.dept, role="nurse"), self.front, self.patient.user, self.support):
            self.client.force_login(who)
            self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_overlap_and_uneven_windows_are_refused(self):
        self.post(self.doctor, self.doctor)
        self.post(self.doctor, self.doctor, start_time="14:00", end_time="16:00")   # overlaps
        self.post(self.doctor, self.doctor, weekday=2, start_time="09:00", end_time="09:50")  # 50 min / 30
        self.post(self.doctor, self.doctor, weekday=3, start_time="10:00", end_time="09:00")  # backwards
        self.assertEqual(DoctorAvailability.objects.filter(doctor=self.doctor).exclude(weekday=0).count(), 1)

    def test_removing_hours_keeps_booked_appointments(self):
        appt = make_appt(self.patient, self.doctor, at(self.monday, 9))
        window = DoctorAvailability.objects.get(doctor=self.doctor, weekday=0)
        self.client.force_login(self.doctor)
        self.client.post(reverse("appointments:availability_remove", args=[window.pk]))
        self.assertFalse(DoctorAvailability.objects.filter(pk=window.pk).exists())
        appt.refresh_from_db()
        self.assertEqual(appt.status, S.SCHEDULED)
        self.assertTrue(AuditLog.objects.filter(action="availability_removed").exists())

    def test_another_doctor_cannot_remove_my_hours(self):
        window = DoctorAvailability.objects.get(doctor=self.doctor, weekday=0)
        self.client.force_login(make_doctor(self.dept))
        r = self.client.post(reverse("appointments:availability_remove", args=[window.pk]))
        self.assertEqual(r.status_code, 404)
        self.assertTrue(DoctorAvailability.objects.filter(pk=window.pk).exists())
