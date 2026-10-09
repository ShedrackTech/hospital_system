from django.test import TestCase, override_settings
from django.urls import reverse

from cases import services
from cases.tests import PW, make_patient, make_user
from departments.models import Department, StaffProfile


def staff(username, role, dept, category="medical", grade="junior"):
    user = make_user(username)
    user.role = role
    user.save()
    StaffProfile.objects.create(user=user, category=category, job_title="Staff",
                                department=dept, grade=grade)
    return user


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class DashboardTests(TestCase):
    def setUp(self):
        self.general = Department.objects.create(name="General", is_general=True)
        self.surgery = Department.objects.create(name="Surgery")
        self.physio = Department.objects.create(name="Physio")
        self.triage = staff("triage", "nurse", self.general)
        self.head = staff("head", "department_head", self.surgery, grade="senior")
        self.surgery.head = self.head
        self.surgery.save()
        self.doc = staff("doc", "doctor", self.surgery)
        self.doc2 = staff("doc2", "doctor", self.physio)
        self.cleaner = staff("cleaner", "staff", None, category="support")
        self.reception = staff("reception", "staff", None, category="admin")
        self.boss = make_user("boss")
        self.boss.role = "main_admin"
        self.boss.save()

        self.p1 = make_patient("pat1")
        self.p2 = make_patient("pat2")
        # c1: routed to surgery, waiting for assignment
        self.c1 = services.create_case(self.p1, "Chest pain")
        services.route_case(self.c1, self.surgery, self.triage)
        # c2: not routed yet (triage queue)
        self.c2 = services.create_case(self.p2, "Headache")
        # c3: routed and assigned to doc
        self.c3 = services.create_case(self.p1, "Cough")
        services.route_case(self.c3, self.surgery, self.triage)
        services.assign_case(self.c3, self.doc, self.head)

    def dash(self, username):
        self.client.logout()
        self.client.login(username=username, password=PW)
        response = self.client.get(reverse("accounts:dashboard"))
        self.assertEqual(response.status_code, 200)
        return response.context["dash"]

    def test_login_required(self):
        self.assertEqual(self.client.get(reverse("accounts:dashboard")).status_code, 302)

    def test_admin_sees_hospital_totals(self):
        d = self.dash("boss")
        self.assertEqual(d["kind"], "admin")
        self.assertEqual(d["counts"]["total"], 3)
        self.assertEqual(d["counts"]["awaiting_triage"], 1)
        self.assertEqual(d["counts"]["awaiting_assignment"], 1)
        self.assertEqual(d["counts"]["assigned"], 1)

    def test_head_sees_only_own_department(self):
        d = self.dash("head")
        self.assertEqual(d["kind"], "head")
        self.assertEqual(d["counts"]["awaiting"], 1)
        self.assertEqual(d["counts"]["assigned"], 1)
        self.assertEqual([c.pk for c in d["waiting"]], [self.c1.pk])
        self.assertEqual(d["team"], 2)  # head and doc

    def test_general_staff_see_triage_queue(self):
        d = self.dash("triage")
        self.assertEqual(d["kind"], "general")
        self.assertEqual(d["waiting_count"], 1)
        self.assertEqual([c.pk for c in d["waiting"]], [self.c2.pk])

    def test_doctor_sees_only_assigned_cases(self):
        d = self.dash("doc")
        self.assertEqual(d["kind"], "medical")
        self.assertEqual(d["counts"]["assigned"], 1)
        self.assertEqual([c.pk for c in d["active"]], [self.c3.pk])
        other = self.dash("doc2")
        self.assertEqual(other["counts"]["assigned"], 0)
        self.assertEqual(other["active"], [])

    def test_patient_sees_only_own_cases(self):
        d = self.dash("pat1")
        self.assertEqual(d["kind"], "patient")
        self.assertEqual({c.pk for c in d["cases"]}, {self.c1.pk, self.c3.pk})
        d2 = self.dash("pat2")
        self.assertEqual({c.pk for c in d2["cases"]}, {self.c2.pk})

    def test_support_staff_get_no_patient_data(self):
        d = self.dash("cleaner")
        self.assertEqual(d["kind"], "support")
        for key in ("counts", "cases", "waiting", "active", "recent_audit"):
            self.assertNotIn(key, d)

    def test_front_desk(self):
        self.assertEqual(self.dash("reception")["kind"], "front_desk")

    def test_every_dashboard_page_renders_for_each_role(self):
        for name in ("boss", "head", "triage", "doc", "pat1", "cleaner", "reception"):
            self.client.logout()
            self.client.login(username=name, password=PW)
            response = self.client.get(reverse("accounts:dashboard"))
            self.assertEqual(response.status_code, 200, name)
