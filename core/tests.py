from django.test import TestCase, override_settings
from django.urls import reverse

from cases import services as case_services
from cases.tests import PW, make_patient, make_staff
from departments.models import Department
from facilities import services as facility_services
from facilities.models import Bed, Building, Ward

from .audit import log
from .models import AuditLog

FAST = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


@FAST
class AuditLogModelTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name="Surgery")
        self.doc = make_staff("doc", self.dept)
        self.patient = make_patient("pat1")

    def test_log_snapshots_actor_and_target(self):
        entry = log(self.doc, "case_viewed", self.patient, patient=self.patient, detail="x")
        self.assertEqual(entry.actor, self.doc)
        self.assertIn("doc", entry.actor_label)
        self.assertEqual(entry.target_type, "patients.patient")
        self.assertEqual(entry.target_id, self.patient.pk)
        self.assertEqual(entry.patient, self.patient)

    def test_anonymous_actor_is_stored_as_none(self):
        from django.contrib.auth.models import AnonymousUser
        entry = log(AnonymousUser(), "something")
        self.assertIsNone(entry.actor)
        self.assertEqual(entry.actor_label, "")

    def test_entries_cannot_be_changed_or_deleted(self):
        entry = log(self.doc, "case_viewed")
        entry.detail = "tampered"
        with self.assertRaises(RuntimeError):
            entry.save()
        with self.assertRaises(RuntimeError):
            entry.delete()

    def test_label_survives_account_changes(self):
        entry = log(self.doc, "case_viewed")
        label = entry.actor_label
        self.doc.delete()
        entry.refresh_from_db()
        self.assertIsNone(entry.actor)
        self.assertEqual(entry.actor_label, label)


@FAST
class AuditIntegrationTests(TestCase):
    def setUp(self):
        self.general = Department.objects.create(name="General", is_general=True)
        self.surgery = Department.objects.create(name="Surgery")
        self.triage = make_staff("triage", self.general)
        self.head = make_staff("head", self.surgery, grade="senior")
        self.surgery.head = self.head
        self.surgery.save()
        self.doc = make_staff("doc", self.surgery)
        self.p1 = make_patient("pat1")

    def actions(self):
        return list(AuditLog.objects.order_by("id").values_list("action", flat=True))

    def test_case_workflow_is_audited(self):
        case = case_services.create_case(self.p1, "Chest pain", actor=self.p1.user)
        case_services.route_case(case, self.surgery, self.triage)
        case_services.assign_case(case, self.doc, self.head)
        case_services.change_status(case, "in_treatment", self.doc)
        self.assertEqual(
            self.actions(),
            ["case_created", "case_routed", "case_assigned", "case_status"],
        )
        routed = AuditLog.objects.get(action="case_routed")
        self.assertEqual(routed.patient, self.p1)
        self.assertIn("triage", routed.actor_label)

    def test_admission_and_discharge_are_audited(self):
        case = case_services.create_case(self.p1, "Chest pain")
        case_services.route_case(case, self.surgery, self.triage)
        case_services.assign_case(case, self.doc, self.head)
        ward = Ward.objects.create(name="W", building=Building.objects.create(name="A"))
        bed = Bed.objects.create(ward=ward, number="1")
        adm = facility_services.admit_patient(case, bed, self.doc)
        facility_services.discharge_patient(adm, self.doc)
        self.assertIn("patient_admitted", self.actions())
        self.assertIn("patient_discharged", self.actions())

    def test_staff_viewing_a_case_is_logged_patient_viewing_own_is_not(self):
        case = case_services.create_case(self.p1, "Chest pain")
        case_services.route_case(case, self.surgery, self.triage)
        case_services.assign_case(case, self.doc, self.head)
        url = reverse("cases:detail", args=[case.pk])

        self.client.login(username="pat1", password=PW)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(AuditLog.objects.filter(action="case_viewed").count(), 0)

        self.client.logout()
        self.client.login(username="doc", password=PW)
        self.assertEqual(self.client.get(url).status_code, 200)
        entry = AuditLog.objects.get(action="case_viewed")
        self.assertEqual(entry.patient, self.p1)
        self.assertIn("doc", entry.actor_label)
        self.assertEqual(entry.ip_address, "127.0.0.1")

    def test_failed_action_leaves_no_audit_entry(self):
        case = case_services.create_case(self.p1, "Chest pain")
        before = AuditLog.objects.count()
        with self.assertRaises(Exception):
            case_services.assign_case(case, self.doc, self.head)  # not routed yet
        self.assertEqual(AuditLog.objects.count(), before)
