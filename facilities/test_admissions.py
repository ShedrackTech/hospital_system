from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from cases import services as case_services
from cases.models import CaseEvent
from cases.tests import PW, make_patient, make_staff
from departments.models import Department

from . import services
from .models import Admission, Bed, Building, Ward


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class AdmissionBase(TestCase):
    def setUp(self):
        self.general = Department.objects.create(name="General", is_general=True)
        self.surgery = Department.objects.create(name="Surgery")
        self.physio = Department.objects.create(name="Physio")
        self.triage = make_staff("triage", self.general)
        self.head = make_staff("head", self.surgery, grade="senior")
        self.surgery.head = self.head
        self.surgery.save()
        self.doc = make_staff("doc", self.surgery)
        self.other = make_staff("other", self.physio)
        self.cleaner = make_staff("cleaner", None, category="support")
        self.p1 = make_patient("pat1")

        self.case = case_services.create_case(self.p1, "Chest pain")
        case_services.route_case(self.case, self.surgery, self.triage)
        case_services.assign_case(self.case, self.doc, self.head)
        case_services.change_status(self.case, "in_treatment", self.doc)
        self.case.refresh_from_db()

        building = Building.objects.create(name="Block A")
        self.ward = Ward.objects.create(name="General Ward", building=building)
        self.bed1 = Bed.objects.create(ward=self.ward, number="1")
        self.bed2 = Bed.objects.create(ward=self.ward, number="2")


class ServiceTests(AdmissionBase):
    def test_admit_occupies_bed_and_logs(self):
        adm = services.admit_patient(self.case, self.bed1, self.doc)
        self.bed1.refresh_from_db()
        self.assertTrue(self.bed1.is_occupied)
        self.assertTrue(adm.is_active)
        self.assertTrue(self.case.events.filter(action=CaseEvent.Action.ADMITTED).exists())

    def test_cannot_use_occupied_bed(self):
        services.admit_patient(self.case, self.bed1, self.doc)
        other_case = case_services.create_case(make_patient("pat2"), "Fever")
        case_services.route_case(other_case, self.surgery, self.triage)
        case_services.assign_case(other_case, self.doc, self.head)
        with self.assertRaises(ValidationError):
            services.admit_patient(other_case, self.bed1, self.doc)

    def test_cannot_admit_twice(self):
        services.admit_patient(self.case, self.bed1, self.doc)
        with self.assertRaises(ValidationError):
            services.admit_patient(self.case, self.bed2, self.doc)

    def test_pending_case_cannot_be_admitted(self):
        pending = case_services.create_case(make_patient("pat3"), "Cough")
        with self.assertRaises(ValidationError):
            services.admit_patient(pending, self.bed1, self.doc)

    def test_other_departments_ward_rejected(self):
        ward = Ward.objects.create(
            name="Physio Ward", building=self.ward.building, department=self.physio
        )
        bed = Bed.objects.create(ward=ward, number="1")
        with self.assertRaises(ValidationError):
            services.admit_patient(self.case, bed, self.doc)

    def test_discharge_frees_bed(self):
        adm = services.admit_patient(self.case, self.bed1, self.doc)
        services.discharge_patient(adm, self.doc)
        self.bed1.refresh_from_db()
        self.assertFalse(self.bed1.is_occupied)
        self.assertIsNotNone(Admission.objects.get(pk=adm.pk).discharged_at)
        with self.assertRaises(ValidationError):
            services.discharge_patient(adm, self.doc)

    def test_cannot_complete_case_while_admitted(self):
        adm = services.admit_patient(self.case, self.bed1, self.doc)
        with self.assertRaises(ValidationError):
            case_services.change_status(self.case, "completed", self.doc)
        services.discharge_patient(adm, self.doc)
        done = case_services.change_status(self.case, "completed", self.doc)
        self.assertEqual(done.status, "completed")


class ViewTests(AdmissionBase):
    def login(self, username):
        self.client.login(username=username, password=PW)

    def test_login_required(self):
        r = self.client.get(reverse("facilities:admit", args=[self.case.pk]))
        self.assertEqual(r.status_code, 302)

    def test_assigned_doctor_admits(self):
        self.login("doc")
        r = self.client.post(reverse("facilities:admit", args=[self.case.pk]),
                             {"bed": self.bed1.pk})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Admission.objects.filter(case=self.case).count(), 1)

    def test_head_can_open_admit_page(self):
        self.login("head")
        r = self.client.get(reverse("facilities:admit", args=[self.case.pk]))
        self.assertEqual(r.status_code, 200)

    def test_unrelated_staff_get_404(self):
        for name in ("other", "cleaner"):
            self.client.logout()
            self.login(name)
            r = self.client.post(reverse("facilities:admit", args=[self.case.pk]),
                                 {"bed": self.bed1.pk})
            self.assertEqual(r.status_code, 404)
        self.assertEqual(Admission.objects.count(), 0)

    def test_patient_cannot_admit_themselves(self):
        self.login("pat1")
        r = self.client.post(reverse("facilities:admit", args=[self.case.pk]),
                             {"bed": self.bed1.pk})
        self.assertEqual(r.status_code, 403)

    def test_doctor_discharges(self):
        adm = services.admit_patient(self.case, self.bed1, self.doc)
        self.login("doc")
        r = self.client.post(reverse("facilities:discharge", args=[adm.pk]))
        self.assertEqual(r.status_code, 302)
        self.bed1.refresh_from_db()
        self.assertFalse(self.bed1.is_occupied)
