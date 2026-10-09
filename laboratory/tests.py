from django.test import TestCase, override_settings
from django.urls import reverse

from cases import services as case_services
from cases.tests import PW, make_patient, make_user
from core.models import AuditLog
from departments.models import Department, StaffProfile

from . import services
from .models import LabResult, LabTest

FAST = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


def staff(username, role, dept, category="medical", grade="junior"):
    user = make_user(username)
    user.role = role
    user.save()
    StaffProfile.objects.create(user=user, category=category, job_title="Staff",
                                department=dept, grade=grade)
    return user


@FAST
class LabBase(TestCase):
    def setUp(self):
        self.lab = Department.objects.create(name="Laboratory", is_laboratory=True)
        self.surgery = Department.objects.create(name="Surgery")
        self.head = staff("head", "department_head", self.surgery, grade="senior")
        self.surgery.head = self.head
        self.surgery.save()
        self.doc = staff("doc", "doctor", self.surgery)
        self.other_doc = staff("otherdoc", "doctor", self.surgery)
        self.tech = staff("tech", "staff", self.lab)
        self.senior_tech = staff("seniortech", "senior_staff", self.lab, grade="senior")
        self.cleaner = staff("cleaner", "staff", None, category="support")
        self.p1 = make_patient("pat1")
        self.p2 = make_patient("pat2")

        self.case = case_services.create_case(self.p1, "Fever")
        case_services.route_case(self.case, self.surgery, self.head)
        case_services.assign_case(self.case, self.doc, self.head)
        case_services.change_status(self.case, "in_treatment", self.doc)
        self.case.refresh_from_db()

        self.test_a = LabTest.objects.create(name="Malaria test", unit="", reference_range="Negative")
        self.test_b = LabTest.objects.create(name="Haemoglobin", unit="g/dL", reference_range="12 - 16")

    def login(self, username):
        self.client.logout()
        self.assertTrue(self.client.login(username=username, password=PW))

    def released_result(self):
        result = services.order_tests(self.case, [self.test_a], self.doc)[0]
        services.enter_result(result, "Positive", "", self.tech)
        services.release_result(result, self.doc)
        result.refresh_from_db()
        return result


class ServiceTests(LabBase):
    def test_order_creates_ordered_results_for_the_cases_patient(self):
        results = services.order_tests(self.case, [self.test_a, self.test_b], self.doc)
        self.assertEqual(len(results), 2)
        self.assertTrue(all(r.status == "ordered" and r.patient == self.p1 for r in results))

    def test_cannot_order_nothing_or_for_a_pending_case(self):
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            services.order_tests(self.case, [], self.doc)
        pending = case_services.create_case(self.p2, "Cough")
        with self.assertRaises(ValidationError):
            services.order_tests(pending, [self.test_a], self.doc)

    def test_workflow_order_enter_release(self):
        result = self.released_result()
        self.assertEqual(result.status, "released")
        self.assertEqual(result.entered_by, self.tech)
        self.assertEqual(result.released_by, self.doc)

    def test_steps_cannot_be_skipped_or_repeated(self):
        from django.core.exceptions import ValidationError
        result = services.order_tests(self.case, [self.test_a], self.doc)[0]
        with self.assertRaises(ValidationError):
            services.release_result(result, self.doc)  # nothing entered yet
        services.enter_result(result, "Negative", "", self.tech)
        with self.assertRaises(ValidationError):
            services.enter_result(result, "Positive", "", self.tech)  # already entered

    def test_cancel_only_before_a_result_exists(self):
        from django.core.exceptions import ValidationError
        result = services.order_tests(self.case, [self.test_a], self.doc)[0]
        services.cancel_result(result, self.doc, "ordered by mistake")
        result.refresh_from_db()
        self.assertEqual(result.status, "cancelled")
        with self.assertRaises(ValidationError):
            services.enter_result(result, "x", "", self.tech)

    def test_audit_entries_exist_and_never_hold_the_value(self):
        self.released_result()
        actions = set(AuditLog.objects.values_list("action", flat=True))
        self.assertTrue({"lab_ordered", "lab_result_entered", "lab_result_released"} <= actions)
        for entry in AuditLog.objects.filter(action__startswith="lab_"):
            self.assertNotIn("Positive", entry.detail)


class ViewTests(LabBase):
    def test_only_assigned_doctor_or_head_can_order(self):
        url = reverse("laboratory:order", args=[self.case.pk])
        self.login("doc")
        r = self.client.post(url, {"tests": [self.test_a.pk]})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(LabResult.objects.count(), 1)
        self.login("otherdoc")
        self.assertEqual(self.client.post(url, {"tests": [self.test_a.pk]}).status_code, 404)
        self.login("pat1")  # can see the case, cannot order
        self.assertEqual(self.client.post(url, {"tests": [self.test_a.pk]}).status_code, 403)
        self.assertEqual(LabResult.objects.count(), 1)

    def test_only_lab_staff_enter_results(self):
        result = services.order_tests(self.case, [self.test_a], self.doc)[0]
        url = reverse("laboratory:result_enter", args=[result.pk])
        self.login("doc")
        self.assertEqual(self.client.post(url, {"value": "Positive"}).status_code, 403)
        self.login("tech")
        self.assertEqual(self.client.post(url, {"value": "Positive"}).status_code, 302)
        result.refresh_from_db()
        self.assertEqual(result.status, "resulted")

    def test_only_a_clinician_or_senior_lab_staff_release(self):
        result = services.order_tests(self.case, [self.test_a], self.doc)[0]
        services.enter_result(result, "Positive", "", self.tech)
        url = reverse("laboratory:result_release", args=[result.pk])
        self.login("tech")  # junior lab staff
        self.assertEqual(self.client.post(url).status_code, 403)
        self.login("seniortech")
        self.assertEqual(self.client.post(url).status_code, 302)
        result.refresh_from_db()
        self.assertEqual(result.status, "released")

    def test_patient_sees_results_only_after_release(self):
        result = services.order_tests(self.case, [self.test_a], self.doc)[0]
        self.login("pat1")
        self.assertEqual(self.client.get(reverse("laboratory:result", args=[result.pk])).status_code, 404)
        services.enter_result(result, "Positive", "", self.tech)
        self.assertEqual(self.client.get(reverse("laboratory:result", args=[result.pk])).status_code, 404)
        self.assertEqual(list(self.client.get(reverse("laboratory:mine")).context["results"]), [])
        services.release_result(result, self.doc)
        self.assertEqual(self.client.get(reverse("laboratory:result", args=[result.pk])).status_code, 200)
        self.assertEqual(len(self.client.get(reverse("laboratory:mine")).context["results"]), 1)

    def test_patient_cannot_see_another_patients_result(self):
        result = self.released_result()
        self.login("pat2")
        self.assertEqual(self.client.get(reverse("laboratory:result", args=[result.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("laboratory:print", args=[result.pk])).status_code, 404)
        self.assertEqual(list(self.client.get(reverse("laboratory:mine")).context["results"]), [])

    def test_print_only_when_released_and_is_audited(self):
        result = services.order_tests(self.case, [self.test_a], self.doc)[0]
        services.enter_result(result, "Positive", "", self.tech)
        self.login("doc")
        self.assertEqual(self.client.get(reverse("laboratory:print", args=[result.pk])).status_code, 403)
        services.release_result(result, self.doc)
        self.login("pat1")
        response = self.client.get(reverse("laboratory:print", args=[result.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Positive")
        self.assertTrue(AuditLog.objects.filter(action="lab_result_printed").exists())

    def test_support_staff_and_unrelated_staff_are_blocked(self):
        result = self.released_result()
        self.login("cleaner")
        self.assertEqual(self.client.get(reverse("laboratory:worklist")).status_code, 403)
        self.assertEqual(self.client.get(reverse("laboratory:result", args=[result.pk])).status_code, 404)
        self.login("otherdoc")
        self.assertEqual(self.client.get(reverse("laboratory:result", args=[result.pk])).status_code, 404)

    def test_catalogue_is_for_lab_staff_and_admins_only(self):
        self.login("doc")
        self.assertEqual(self.client.get(reverse("laboratory:tests")).status_code, 403)
        self.login("tech")
        r = self.client.post(reverse("laboratory:test_create"),
                             {"name": "Blood sugar", "unit": "mmol/L",
                              "reference_range": "4 - 7", "is_active": "on"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(LabTest.objects.filter(name="Blood sugar").exists())

    def test_pages_render(self):
        result = services.order_tests(self.case, [self.test_a], self.doc)[0]
        self.login("tech")
        for name, args in (("laboratory:worklist", []), ("laboratory:tests", []),
                           ("laboratory:result", [result.pk])):
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 200, name)
        self.login("doc")
        self.assertEqual(self.client.get(reverse("laboratory:order", args=[self.case.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("cases:detail", args=[self.case.pk])).status_code, 200)

    def test_dashboards_for_lab_staff_and_patients(self):
        self.login("tech")
        self.assertEqual(self.client.get(reverse("accounts:dashboard")).context["dash"]["kind"], "lab")
        self.released_result()
        self.login("pat1")
        dash = self.client.get(reverse("accounts:dashboard")).context["dash"]
        self.assertEqual(dash["results_count"], 1)
