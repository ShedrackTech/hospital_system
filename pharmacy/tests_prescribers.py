"""Who may prescribe: the assigned doctor, the assigned senior nurse, or the department head."""
from django.urls import reverse

from cases.models import Case

from . import permissions as perms
from . import services
from . import tests as base
from .models import Prescription


@base.FAST
class PrescriberRuleTests(base.PharmacyBase):
    def assign(self, user):
        """Put someone on the case directly, so the test does not depend on assignment rules."""
        Case.objects.filter(pk=self.case.pk).update(assigned_to=user)
        self.case.refresh_from_db()

    def test_assigned_doctor_and_senior_doctor_can_prescribe(self):
        self.assertTrue(perms.can_prescribe(self.doc, self.case))
        senior_doc = base.staff("seniordoc", "senior_doctor", self.surgery, grade="senior")
        self.assign(senior_doc)
        self.assertTrue(perms.can_prescribe(senior_doc, self.case))

    def test_assigned_senior_nurse_can_prescribe(self):
        nurse = base.staff("seniornurse", "senior_nurse", self.surgery, grade="senior")
        self.assign(nurse)
        self.assertTrue(perms.can_prescribe(nurse, self.case))

    def test_unassigned_senior_nurse_cannot(self):
        nurse = base.staff("seniornurse", "senior_nurse", self.surgery, grade="senior")
        self.assertFalse(perms.can_prescribe(nurse, self.case))

    def test_junior_nurse_cannot_even_when_assigned(self):
        nurse = base.staff("nurse1", "nurse", self.surgery)
        self.assign(nurse)
        self.assertFalse(perms.can_prescribe(nurse, self.case))

    def test_other_staff_roles_cannot_even_when_assigned(self):
        for role in ("staff", "senior_staff"):
            user = base.staff(f"u_{role}", role, self.surgery)
            self.assign(user)
            self.assertFalse(perms.can_prescribe(user, self.case), role)

    def test_pharmacy_staff_never_prescribe(self):
        for user in (self.pharm, self.senior_pharm, self.pharm_head):
            self.assertFalse(perms.can_prescribe(user, self.case), user.username)
        self.assign(self.pharm)  # even if someone assigned them to the case by mistake
        self.assertFalse(perms.can_prescribe(self.pharm, self.case))

    def test_department_head_can_still_prescribe(self):
        self.assertTrue(perms.can_prescribe(self.head, self.case))

    def test_nurse_cannot_cancel_a_prescription_but_senior_nurse_can(self):
        rx = services.prescribe(self.case, [base.item(self.para)], self.doc)
        junior = base.staff("nurse1", "nurse", self.surgery)
        self.assign(junior)
        rx = Prescription.objects.get(pk=rx.pk)
        self.assertFalse(perms.can_cancel(junior, rx))
        senior = base.staff("seniornurse", "senior_nurse", self.surgery, grade="senior")
        self.assign(senior)
        rx = Prescription.objects.get(pk=rx.pk)
        self.assertTrue(perms.can_cancel(senior, rx))

    def test_assigned_nurse_can_still_see_the_prescriptions_of_the_case(self):
        rx = services.prescribe(self.case, [base.item(self.para)], self.doc)
        nurse = base.staff("nurse1", "nurse", self.surgery)
        self.assign(nurse)
        rx = Prescription.objects.get(pk=rx.pk)
        self.assertTrue(perms.can_view(nurse, rx))

    def test_prescribe_page_is_closed_to_a_junior_nurse_and_open_to_a_senior_nurse(self):
        junior = base.staff("nurse1", "nurse", self.surgery)
        senior = base.staff("seniornurse", "senior_nurse", self.surgery, grade="senior")
        url = reverse("pharmacy:prescribe", args=[self.case.pk])
        self.assign(junior)
        self.login("nurse1")
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assign(senior)
        self.login("seniornurse")
        self.assertEqual(self.client.get(url).status_code, 200)


@base.FAST
class BackLinkTests(base.PharmacyBase):
    def test_back_link_goes_somewhere_each_role_can_open(self):
        rx = services.prescribe(self.case, [base.item(self.para)], self.doc)
        url = reverse("pharmacy:prescription", args=[rx.pk])
        worklist = reverse("pharmacy:worklist")
        case_page = reverse("cases:detail", args=[self.case.pk])
        for username, expected in (("pharm", worklist), ("pharmhead", worklist), ("doc", case_page),
                                   ("pat1", reverse("pharmacy:mine"))):
            self.login(username)
            self.assertContains(self.client.get(url), f'href="{expected}">Back', msg_prefix=username)