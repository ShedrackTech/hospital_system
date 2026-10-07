from django.test import TestCase, override_settings

from departments.models import Department
from patients.forms import PatientRegistrationForm
from patients.models import Patient
from .models import Case


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class RegistrationCreatesCaseTests(TestCase):
    def data(self, **extra):
        d = {
            "first_name": "Ada", "last_name": "Obi", "username": "adaobi",
            "phone": "08031234567", "date_of_birth": "1990-01-01",
            "gender": Patient.Gender.choices[0][0],
            "password1": "Str0ng!pass99", "password2": "Str0ng!pass99",
        }
        d.update(extra)
        return d

    def test_complaint_opens_pending_unrouted_case(self):
        physio = Department.objects.create(name="Physiotherapy")
        form = PatientRegistrationForm(self.data(complaint="Back pain", department=physio.pk))
        self.assertTrue(form.is_valid(), form.errors)
        patient = form.save()
        case = Case.objects.get(patient=patient)
        self.assertEqual(case.status, "pending")
        self.assertEqual(case.department, physio)
        self.assertFalse(case.is_routed)  # general staff still confirm

    def test_no_complaint_no_case(self):
        form = PatientRegistrationForm(self.data())
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertEqual(Case.objects.count(), 0)

    def test_department_without_complaint_rejected(self):
        physio = Department.objects.create(name="Physiotherapy")
        form = PatientRegistrationForm(self.data(department=physio.pk))
        self.assertFalse(form.is_valid())
        self.assertIn("complaint", form.errors)
