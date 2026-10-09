from django.test import TestCase, override_settings
from django.urls import reverse

from cases.tests import PW, make_patient, make_user
from departments.models import StaffProfile

FAST = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


def person(username, role, category=None):
    user = make_user(username)
    user.role = role
    user.save()
    if category:
        StaffProfile.objects.create(user=user, category=category, job_title="Staff",
                                    department=None, grade="junior")
    return user


@FAST
class FrontDeskAccessTests(TestCase):
    """Only the front desk (administrative staff) and admins register patients and use the card desk."""

    def setUp(self):
        person("desk", "staff", "admin")
        person("boss", "main_admin")
        person("sub", "sub_admin")
        person("doc", "doctor", "medical")
        person("cleaner", "staff", "support")
        make_patient("pat1")

    def get(self, username, name):
        self.client.logout()
        self.assertTrue(self.client.login(username=username, password=PW))
        return self.client.get(reverse(name)).status_code

    def test_front_desk_and_admins_can_register_patients(self):
        for name in ("desk", "boss", "sub"):
            self.assertEqual(self.get(name, "patients:staff_register"), 200, name)

    def test_other_staff_and_patients_cannot_register_patients(self):
        for name in ("doc", "cleaner", "pat1"):
            self.assertEqual(self.get(name, "patients:staff_register"), 403, name)

    def test_card_desk_has_the_same_rule(self):
        self.assertEqual(self.get("desk", "patients:card_desk"), 200)
        for name in ("doc", "cleaner", "pat1"):
            self.assertEqual(self.get(name, "patients:card_desk"), 403, name)

    def test_menu_link_only_for_front_desk_and_admins(self):
        self.client.login(username="doc", password=PW)
        page = self.client.get(reverse("accounts:dashboard"))
        self.assertNotContains(page, reverse("patients:staff_register"))
        self.client.logout()
        self.client.login(username="desk", password=PW)
        page = self.client.get(reverse("accounts:dashboard"))
        self.assertContains(page, reverse("patients:staff_register"))
