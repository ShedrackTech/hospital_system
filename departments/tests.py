from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .forms import StaffProfileForm
from .models import Department, StaffProfile

User = get_user_model()


class DepartmentAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.sub_admin = User.objects.create_user(
            "subadmin", password="pass12345", role=User.Role.SUB_ADMIN
        )
        cls.head = User.objects.create_user(
            "physiohead", password="pass12345", role=User.Role.DEPARTMENT_HEAD
        )
        cls.nurse = User.objects.create_user(
            "nurse1", password="pass12345", role=User.Role.NURSE
        )
        cls.patient = User.objects.create_user(
            "patient1", password="pass12345", role=User.Role.PATIENT
        )
        cls.physio = Department.objects.create(name="Physiotherapy", head=cls.head)
        cls.dietetics = Department.objects.create(name="Dietetics")
        StaffProfile.objects.create(
            user=cls.nurse,
            category=StaffProfile.Category.MEDICAL,
            job_title="Nurse",
            department=cls.dietetics,
        )

    def test_anonymous_is_sent_to_login(self):
        response = self.client.get(reverse("departments:list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_patient_gets_403(self):
        self.client.force_login(self.patient)
        response = self.client.get(reverse("departments:list"))
        self.assertEqual(response.status_code, 403)

    def test_sub_admin_sees_all_departments(self):
        self.client.force_login(self.sub_admin)
        response = self.client.get(reverse("departments:list"))
        self.assertContains(response, "Physiotherapy")
        self.assertContains(response, "Dietetics")

    def test_head_sees_only_own_department(self):
        self.client.force_login(self.head)
        response = self.client.get(reverse("departments:list"))
        self.assertContains(response, "Physiotherapy")
        self.assertNotContains(response, "Dietetics")
        other = self.client.get(reverse("departments:detail", args=[self.dietetics.pk]))
        self.assertEqual(other.status_code, 404)

    def test_staff_sees_only_own_department(self):
        self.client.force_login(self.nurse)
        response = self.client.get(reverse("departments:list"))
        self.assertContains(response, "Dietetics")
        self.assertNotContains(response, "Physiotherapy")

    def test_non_admin_cannot_create_department(self):
        self.client.force_login(self.head)
        response = self.client.post(
            reverse("departments:create"), {"name": "Surgery", "is_active": "on"}
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Department.objects.filter(name="Surgery").exists())

    def test_sub_admin_can_create_department(self):
        self.client.force_login(self.sub_admin)
        response = self.client.post(
            reverse("departments:create"), {"name": "Surgery", "is_active": "on"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Department.objects.filter(name="Surgery").exists())

    def test_staff_profile_form_excludes_patients_and_profiled_users(self):
        users = StaffProfileForm().fields["user"].queryset
        self.assertNotIn(self.patient, users)
        self.assertNotIn(self.nurse, users)
        self.assertIn(self.head, users)
