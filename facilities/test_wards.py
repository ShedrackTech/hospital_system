from django.test import TestCase, override_settings
from django.urls import reverse

from cases import services as case_services
from cases.tests import PW, make_patient, make_user
from core.models import AuditLog
from departments.models import Department, StaffProfile

from . import services
from .models import Bed, Building, Ward, WardAssignment

FAST = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


def person(username, role, dept=None, category="medical"):
    user = make_user(username)
    user.role = role
    user.save()
    StaffProfile.objects.create(user=user, category=category, job_title="Staff",
                                department=dept, grade="junior")
    return user


@FAST
class WardBase(TestCase):
    def setUp(self):
        self.nursing = Department.objects.create(name="Nursing")
        self.surgery = Department.objects.create(name="Surgery")
        self.head = person("head", "department_head", self.nursing)
        self.nursing.head = self.head
        self.nursing.save()
        self.nurse1 = person("nurse1", "nurse", self.nursing)
        self.nurse2 = person("nurse2", "nurse", self.surgery)
        self.doc = person("doc", "doctor", self.surgery)
        self.cleaner = person("cleaner", "staff", None, category="support")
        self.boss = make_user("boss")
        self.boss.role = "main_admin"
        self.boss.save()

        building = Building.objects.create(name="Block A")
        self.w1 = Ward.objects.create(name="Ward 1", building=building)
        self.w2 = Ward.objects.create(name="Ward 2", building=building)
        self.bed1 = Bed.objects.create(ward=self.w1, number="1")
        self.bed2 = Bed.objects.create(ward=self.w2, number="1")

        self.p1, self.p2 = make_patient("pat1"), make_patient("pat2")
        self.case1 = self.admit(self.p1, self.bed1)
        self.case2 = self.admit(self.p2, self.bed2)

    def admit(self, patient, bed):
        case = case_services.create_case(patient, "Fever")
        case_services.route_case(case, self.surgery, self.head)
        case_services.assign_case(case, self.doc, self.head)
        case_services.change_status(case, "in_treatment", self.doc)
        services.admit_patient(case, bed, self.doc)
        return case

    def login(self, username):
        self.client.logout()
        self.assertTrue(self.client.login(username=username, password=PW))

    def assign(self, nurse, ward):
        return WardAssignment.objects.create(user=nurse, ward=ward)


class ManagementTests(WardBase):
    def test_admin_assigns_a_nurse_and_it_is_audited(self):
        self.login("boss")
        response = self.client.post(reverse("facilities:ward_assign"),
                                    {"nurses": [self.nurse1.pk], "ward": self.w1.pk})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(WardAssignment.objects.filter(user=self.nurse1, ward=self.w1).exists())
        self.assertTrue(AuditLog.objects.filter(action="ward_staff_assigned").exists())

    def test_assigning_twice_does_not_duplicate(self):
        self.login("boss")
        data = {"nurses": [self.nurse1.pk], "ward": self.w1.pk}
        self.client.post(reverse("facilities:ward_assign"), data)
        self.client.post(reverse("facilities:ward_assign"), data)
        self.assertEqual(WardAssignment.objects.filter(user=self.nurse1).count(), 1)

    def test_head_assigns_only_their_own_team(self):
        self.login("head")
        self.client.post(reverse("facilities:ward_assign"),
                         {"nurses": [self.nurse2.pk], "ward": self.w1.pk})  # Surgery nurse
        self.assertEqual(WardAssignment.objects.count(), 0)
        self.client.post(reverse("facilities:ward_assign"),
                         {"nurses": [self.nurse1.pk], "ward": self.w1.pk})  # Nursing nurse
        self.assertEqual(WardAssignment.objects.filter(user=self.nurse1).count(), 1)

    def test_only_nurses_can_be_assigned(self):
        self.login("boss")
        self.client.post(reverse("facilities:ward_assign"),
                         {"nurses": [self.doc.pk, self.cleaner.pk], "ward": self.w1.pk})
        self.assertEqual(WardAssignment.objects.count(), 0)

    def test_removal_rules_and_audit(self):
        mine = self.assign(self.nurse1, self.w1)
        other = self.assign(self.nurse2, self.w1)
        self.login("head")
        self.assertEqual(self.client.post(reverse("facilities:ward_unassign", args=[other.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("facilities:ward_unassign", args=[mine.pk])).status_code, 302)
        self.assertFalse(WardAssignment.objects.filter(pk=mine.pk).exists())
        self.assertTrue(AuditLog.objects.filter(action="ward_staff_removed").exists())

    def test_manager_page_access(self):
        for name, code in (("boss", 200), ("head", 200), ("nurse1", 403), ("doc", 403), ("pat1", 403)):
            self.login(name)
            self.assertEqual(self.client.get(reverse("facilities:ward_staff")).status_code, code, name)


class NurseAccessTests(WardBase):
    def setUp(self):
        super().setUp()
        self.assign(self.nurse1, self.w1)

    def test_nurse_sees_only_patients_in_their_ward_and_it_is_audited(self):
        self.login("nurse1")
        page = self.client.get(reverse("facilities:my_ward"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, self.p1.user.login_id)
        self.assertNotContains(page, self.p2.user.login_id)
        self.assertTrue(AuditLog.objects.filter(action="ward_list_viewed").exists())

    def test_nurse_opens_the_case_of_a_patient_in_their_ward_only(self):
        self.login("nurse1")
        self.assertEqual(self.client.get(reverse("cases:detail", args=[self.case1.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("cases:detail", args=[self.case2.pk])).status_code, 404)
        self.assertTrue(AuditLog.objects.filter(action="case_viewed", patient=self.p1).exists())

    def test_access_ends_when_the_patient_is_discharged(self):
        from .models import Admission
        services.discharge_patient(Admission.objects.get(case=self.case1), self.doc)
        self.login("nurse1")
        self.assertEqual(self.client.get(reverse("cases:detail", args=[self.case1.pk])).status_code, 404)

    def test_nurse_access_is_read_only(self):
        self.login("nurse1")
        self.assertEqual(self.client.post(reverse("cases:status", args=[self.case1.pk]),
                                          {"status": "completed"}).status_code, 403)
        self.assertEqual(self.client.post(reverse("facilities:discharge", args=[
            self.case1.admissions.get().pk])).status_code, 403)
        self.case1.refresh_from_db()
        self.assertEqual(self.case1.status, "in_treatment")

    def test_a_nurse_without_a_ward_sees_nothing(self):
        other = person("nurse3", "nurse", self.nursing)
        self.login("nurse3")
        page = self.client.get(reverse("facilities:my_ward"))
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context["wards"], [])
        self.assertEqual(self.client.get(reverse("cases:detail", args=[self.case1.pk])).status_code, 404)

    def test_patients_cannot_open_the_ward_page(self):
        self.login("pat1")
        self.assertEqual(self.client.get(reverse("facilities:my_ward")).status_code, 403)

    def test_dashboard_shows_the_ward_count(self):
        self.login("nurse1")
        dash = self.client.get(reverse("accounts:dashboard")).context["dash"]
        self.assertTrue(dash["has_wards"])
        self.assertEqual(dash["ward_patients"], 1)
