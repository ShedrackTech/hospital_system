from datetime import date

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from departments.models import Department, StaffProfile
from patients.models import Patient
from . import services
from .models import Case

User = get_user_model()
PW = "pass12345!"


def make_user(username):
    return User.objects.create_user(username=username, password=PW)


def make_staff(username, dept, category="medical", grade="junior"):
    u = make_user(username)
    StaffProfile.objects.create(user=u, category=category, job_title="Staff",
                                department=dept, grade=grade)
    return u


def make_patient(username):
    return Patient.objects.create(
        user=make_user(username),
        date_of_birth=date(1990, 1, 1),
        gender=Patient.Gender.choices[0][0],
    )


class CaseBase(TestCase):
    def setUp(self):
        self.general = Department.objects.create(name="General", is_general=True)
        self.surgery = Department.objects.create(name="Surgery")
        self.physio = Department.objects.create(name="Physio")
        self.triage = make_staff("triage", self.general)
        self.head = make_staff("head", self.surgery, grade="senior")
        self.surgery.head = self.head
        self.surgery.save()
        self.doc = make_staff("doc", self.surgery)
        self.physio_doc = make_staff("physiodoc", self.physio)
        self.cleaner = make_staff("cleaner", None, category="support")
        self.p1 = make_patient("pat1")
        self.p2 = make_patient("pat2")
        self.case = services.create_case(self.p1, "Chest pain", actor=self.p1.user)


class ServiceTests(CaseBase):
    def test_new_case_pending_and_unrouted(self):
        self.assertEqual(self.case.status, "pending")
        self.assertFalse(self.case.is_routed)
        self.assertEqual(self.case.events.count(), 1)

    def test_empty_complaint_rejected(self):
        with self.assertRaises(ValidationError):
            services.create_case(self.p1, "   ")

    def test_route_sets_department(self):
        c = services.route_case(self.case, self.surgery, self.triage)
        self.assertEqual(c.department, self.surgery)
        self.assertTrue(c.is_routed)
        self.assertEqual(c.routed_by, self.triage)

    def test_cannot_route_twice(self):
        services.route_case(self.case, self.surgery, self.triage)
        with self.assertRaises(ValidationError):
            services.route_case(self.case, self.physio, self.triage)

    def test_assign_requires_routing(self):
        with self.assertRaises(ValidationError):
            services.assign_case(self.case, self.doc, self.head)

    def test_assign_rejects_other_department_staff(self):
        services.route_case(self.case, self.surgery, self.triage)
        with self.assertRaises(ValidationError):
            services.assign_case(self.case, self.physio_doc, self.head)

    def test_full_flow(self):
        services.route_case(self.case, self.surgery, self.triage)
        services.assign_case(self.case, self.doc, self.head)
        services.change_status(self.case, "in_treatment", self.doc)
        c = services.change_status(self.case, "completed", self.doc)
        self.assertEqual(c.status, "completed")
        self.assertEqual(c.events.count(), 5)

    def test_invalid_transition(self):
        services.route_case(self.case, self.surgery, self.triage)
        services.assign_case(self.case, self.doc, self.head)
        with self.assertRaises(ValidationError):
            services.change_status(self.case, "completed", self.doc)

    def test_no_reassign_after_treatment_starts(self):
        services.route_case(self.case, self.surgery, self.triage)
        services.assign_case(self.case, self.doc, self.head)
        services.change_status(self.case, "in_treatment", self.doc)
        with self.assertRaises(ValidationError):
            services.assign_case(self.case, self.head, self.head)


class ViewTests(CaseBase):
    def login(self, username):
        self.client.login(username=username, password=PW)

    def test_login_required(self):
        r = self.client.get(reverse("cases:mine"))
        self.assertEqual(r.status_code, 302)

    def test_patient_sees_only_own_cases(self):
        services.create_case(self.p2, "Headache")
        self.login("pat1")
        r = self.client.get(reverse("cases:mine"))
        self.assertEqual(list(r.context["cases"]), [self.case])

    def test_patient_cannot_open_other_patients_case(self):
        self.login("pat2")
        r = self.client.get(reverse("cases:detail", args=[self.case.pk]))
        self.assertEqual(r.status_code, 404)

    def test_patient_creates_case(self):
        self.login("pat2")
        r = self.client.post(reverse("cases:new"), {"complaint": "Fever"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Case.objects.filter(patient=self.p2).count(), 1)

    def test_triage_queue_access(self):
        self.login("triage")
        self.assertEqual(self.client.get(reverse("cases:triage")).status_code, 200)
        self.client.logout()
        self.login("doc")
        self.assertEqual(self.client.get(reverse("cases:triage")).status_code, 403)

    def test_support_staff_blocked_everywhere(self):
        self.login("cleaner")
        self.assertEqual(self.client.get(reverse("cases:triage")).status_code, 403)
        self.assertEqual(self.client.get(reverse("cases:assigned")).status_code, 403)
        r = self.client.get(reverse("cases:detail", args=[self.case.pk]))
        self.assertEqual(r.status_code, 404)

    def test_triage_routes_via_view(self):
        self.login("triage")
        r = self.client.post(reverse("cases:route", args=[self.case.pk]),
                             {"department": self.surgery.pk})
        self.assertEqual(r.status_code, 302)
        self.case.refresh_from_db()
        self.assertEqual(self.case.department, self.surgery)

    def test_head_assigns_and_others_cannot(self):
        services.route_case(self.case, self.surgery, self.triage)
        url = reverse("cases:assign", args=[self.case.pk])
        self.login("physiodoc")
        self.assertEqual(self.client.post(url, {"assignee": self.doc.pk}).status_code, 404)
        self.client.logout()
        self.login("head")
        self.assertEqual(self.client.post(url, {"assignee": self.doc.pk}).status_code, 302)
        self.case.refresh_from_db()
        self.assertEqual(self.case.assigned_to, self.doc)

    def test_only_assignee_changes_status(self):
        services.route_case(self.case, self.surgery, self.triage)
        services.assign_case(self.case, self.doc, self.head)
        url = reverse("cases:status", args=[self.case.pk])
        self.login("head")
        self.assertEqual(self.client.post(url, {"status": "in_treatment"}).status_code, 403)
        self.client.logout()
        self.login("doc")
        self.assertEqual(self.client.post(url, {"status": "in_treatment"}).status_code, 302)
        self.case.refresh_from_db()
        self.assertEqual(self.case.status, "in_treatment")
