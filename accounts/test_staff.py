from django.test import TestCase, override_settings
from django.urls import reverse

from cases.tests import PW, make_user
from core.models import AuditLog
from departments.models import Department, StaffProfile

from .models import User

FAST = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


def person(username, role, dept=None, category="medical"):
    user = make_user(username)
    user.role = role
    user.save()
    if role != "patient":
        StaffProfile.objects.create(user=user, category=category, job_title="Staff",
                                    department=dept, grade="junior")
    return user


@FAST
class StaffManagementTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name="Surgery")
        self.boss = person("boss", "main_admin")
        self.sub = person("sub", "sub_admin")
        self.sub2 = person("sub2", "sub_admin")
        self.doc = person("doc", "doctor", self.dept)
        self.patient = person("pat", "patient")

    def login(self, username):
        self.client.logout()
        self.assertTrue(self.client.login(username=username, password=PW))

    def data(self, **extra):
        d = {
            "first_name": "New", "last_name": "Person", "username": "newperson",
            "phone": "08031234567", "role": "doctor", "supervisor": "",
            "category": "medical", "job_title": "Doctor", "department": self.dept.pk,
            "grade": "junior", "password1": "Str0ng!pass99", "password2": "Str0ng!pass99",
        }
        d.update(extra)
        return d

    def test_only_admin_roles_can_open_staff_pages(self):
        for name in ("doc", "pat"):
            self.login(name)
            self.assertEqual(self.client.get(reverse("accounts:staff_list")).status_code, 403)

    def test_create_makes_account_profile_and_staff_id(self):
        self.login("sub")
        r = self.client.post(reverse("accounts:staff_create"), self.data())
        self.assertEqual(r.status_code, 302)
        user = User.objects.get(username="newperson")
        self.assertTrue(user.login_id.startswith("STF"))
        self.assertEqual(user.staff_profile.department, self.dept)
        self.assertFalse(user.is_staff)
        self.assertTrue(AuditLog.objects.filter(action="staff_created").exists())

    def test_sub_admin_cannot_create_a_sub_admin_but_main_admin_can(self):
        self.login("sub")
        self.client.post(reverse("accounts:staff_create"),
                         self.data(role="sub_admin", username="newsub1"))
        self.assertFalse(User.objects.filter(username="newsub1").exists())
        self.login("boss")
        self.client.post(reverse("accounts:staff_create"),
                         self.data(role="sub_admin", username="newsub2"))
        created = User.objects.get(username="newsub2")
        self.assertEqual(created.role, "sub_admin")
        self.assertTrue(created.is_staff)

    def test_nobody_manages_self_main_admin_or_other_sub_admin(self):
        self.login("sub")
        for target in (self.sub, self.boss, self.sub2):
            r = self.client.get(reverse("accounts:staff_update", args=[target.pk]))
            self.assertEqual(r.status_code, 403, target.username)

    def test_demoting_a_sub_admin_removes_admin_access(self):
        self.login("boss")
        r = self.client.post(reverse("accounts:staff_update", args=[self.sub2.pk]),
                             self.data(username="sub2", role="doctor"))
        self.assertEqual(r.status_code, 302)
        self.sub2.refresh_from_db()
        self.assertEqual(self.sub2.role, "doctor")
        self.assertFalse(self.sub2.is_staff)

    def test_deactivate_blocks_login_and_removes_head(self):
        self.dept.head = self.doc
        self.dept.save()
        self.login("sub")
        r = self.client.post(reverse("accounts:staff_deactivate", args=[self.doc.pk]))
        self.assertEqual(r.status_code, 302)
        self.doc.refresh_from_db()
        self.dept.refresh_from_db()
        self.assertFalse(self.doc.is_active)
        self.assertIsNone(self.dept.head)
        self.client.logout()
        self.assertFalse(self.client.login(username="doc", password=PW))
        self.assertTrue(AuditLog.objects.filter(action="staff_deactivated").exists())

    def test_reactivate(self):
        self.doc.is_active = False
        self.doc.save()
        self.login("sub")
        self.client.post(reverse("accounts:staff_reactivate", args=[self.doc.pk]))
        self.doc.refresh_from_db()
        self.assertTrue(self.doc.is_active)

    def test_password_reset_works_and_is_not_logged(self):
        self.login("sub")
        r = self.client.post(reverse("accounts:staff_password", args=[self.doc.pk]),
                             {"password1": "Br4nd!newpass", "password2": "Br4nd!newpass"})
        self.assertEqual(r.status_code, 302)
        self.client.logout()
        self.assertTrue(self.client.login(username="doc", password="Br4nd!newpass"))
        entry = AuditLog.objects.get(action="staff_password_reset")
        self.assertNotIn("Br4nd", entry.detail)

    def test_supervisor_loop_is_rejected(self):
        report = person("report", "nurse", self.dept)
        report.supervisor = self.doc
        report.save()
        self.login("sub")
        r = self.client.post(reverse("accounts:staff_update", args=[self.doc.pk]),
                             self.data(username="doc", supervisor=report.pk))
        self.assertEqual(r.status_code, 200)  # form shown again with an error
        self.doc.refresh_from_db()
        self.assertIsNone(self.doc.supervisor)

    def test_list_and_detail_pages_render(self):
        self.login("sub")
        self.assertEqual(self.client.get(reverse("accounts:staff_list")).status_code, 200)
        self.assertEqual(
            self.client.get(reverse("accounts:staff_detail", args=[self.doc.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("accounts:staff_create")).status_code, 200)
        self.assertEqual(
            self.client.get(reverse("accounts:staff_deactivate", args=[self.doc.pk])).status_code, 200)

    def test_patients_do_not_appear_in_staff_pages(self):
        self.login("sub")
        r = self.client.get(reverse("accounts:staff_detail", args=[self.patient.pk]))
        self.assertEqual(r.status_code, 404)
