from datetime import timedelta

from django.contrib.auth import authenticate
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from cases.tests import PW, make_user
from core import lockout
from core.models import AuditLog, LoginThrottle

FAST = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


@FAST
class LockoutTests(TestCase):
    def setUp(self):
        self.user = make_user("ada")
        self.boss = make_user("boss")
        self.boss.role = "main_admin"
        self.boss.save()
        self.doc = make_user("doc")
        self.doc.role = "doctor"
        self.doc.save()

    def attempt(self, who, password=PW):
        return self.client.post(reverse("accounts:login"), {"username": who, "password": password})

    def fail(self, who, times):
        for _ in range(times):
            self.attempt(who, "wrong-password")

    def locked_message(self, response):
        return "Too many failed attempts" in response.content.decode()

    def test_five_wrong_passwords_lock_the_account_even_for_the_right_password(self):
        self.fail("ada", 5)
        response = self.attempt("ada")
        self.assertTrue(self.locked_message(response))
        self.assertContains(response, "15 minutes")
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(AuditLog.objects.filter(action="login_failed").count(), 5)
        self.assertEqual(AuditLog.objects.filter(action="account_locked").count(), 1)
        self.assertTrue(AuditLog.objects.filter(action="login_blocked").exists())

    def test_four_wrong_passwords_do_not_lock(self):
        self.fail("ada", 4)
        self.assertEqual(self.attempt("ada").status_code, 302)

    def test_username_and_card_number_share_one_counter(self):
        self.fail("ada", 3)
        self.fail(self.user.login_id, 2)
        self.assertTrue(self.locked_message(self.attempt("ada")))
        self.assertTrue(self.locked_message(self.attempt(self.user.login_id)))

    def test_unknown_ids_are_locked_with_the_same_message(self):
        self.fail("ghost", 5)
        ghost = self.attempt("ghost", "anything")
        self.fail("ada", 5)
        real = self.attempt("ada", "anything")
        self.assertTrue(self.locked_message(ghost))
        self.assertTrue(self.locked_message(real))
        self.assertContains(ghost, "15 minutes")
        self.assertContains(real, "15 minutes")

    def test_a_correct_login_clears_the_counter(self):
        self.fail("ada", 4)
        self.assertEqual(self.attempt("ada").status_code, 302)
        self.client.logout()
        self.fail("ada", 4)
        self.assertEqual(self.attempt("ada").status_code, 302)

    def test_old_failures_are_forgotten(self):
        self.fail("ada", 4)
        row = LoginThrottle.objects.get(key=f"user:{self.user.pk}")
        row.last_failed_at = timezone.now() - timedelta(minutes=lockout.WINDOW_MINUTES + 5)
        row.save()
        self.fail("ada", 1)
        self.assertEqual(LoginThrottle.objects.get(key=f"user:{self.user.pk}").failed_count, 1)
        self.fail("ada", 3)
        self.assertEqual(self.attempt("ada").status_code, 302)

    def test_the_lock_expires(self):
        self.fail("ada", 5)
        row = LoginThrottle.objects.get(key=f"user:{self.user.pk}")
        row.locked_until = timezone.now() - timedelta(minutes=1)
        row.save()
        self.assertEqual(self.attempt("ada").status_code, 302)

    def test_a_locked_account_cannot_authenticate_by_any_route(self):
        self.fail("ada", 5)
        self.assertIsNone(authenticate(username="ada", password=PW))  # what Django admin uses
        self.assertIsNone(authenticate(username=self.user.login_id, password=PW))

    def test_successful_and_failed_logins_are_audited_with_the_address(self):
        self.fail("ada", 1)
        self.attempt("ada")
        failed = AuditLog.objects.get(action="login_failed")
        success = AuditLog.objects.get(action="login_success")
        self.assertEqual(failed.ip_address, "127.0.0.1")
        self.assertEqual(success.ip_address, "127.0.0.1")
        self.assertIn("ada", failed.detail.lower())

    def test_admin_sees_locked_accounts_and_can_unlock(self):
        self.fail("ada", 5)
        self.assertTrue(self.client.login(username="boss", password=PW))
        page = self.client.get(reverse("accounts:locked_list"))
        self.assertEqual(page.status_code, 200)
        self.assertEqual(len(page.context["locks"]), 1)
        row = page.context["locks"][0]
        self.assertEqual(self.client.post(reverse("accounts:unlock", args=[row.pk])).status_code, 302)
        self.assertTrue(AuditLog.objects.filter(action="account_unlocked").exists())
        self.client.logout()
        self.assertEqual(self.attempt("ada").status_code, 302)

    def test_only_admins_can_see_or_unlock(self):
        self.fail("ada", 5)
        row = LoginThrottle.objects.get(key=f"user:{self.user.pk}")
        self.assertTrue(self.client.login(username="doc", password=PW))
        self.assertEqual(self.client.get(reverse("accounts:locked_list")).status_code, 403)
        self.assertEqual(self.client.post(reverse("accounts:unlock", args=[row.pk])).status_code, 403)
        self.assertTrue(lockout.is_locked("ada"))

    def test_dashboard_counts_locked_accounts(self):
        self.fail("ada", 5)
        self.assertTrue(self.client.login(username="boss", password=PW))
        dash = self.client.get(reverse("accounts:dashboard")).context["dash"]
        self.assertEqual(dash["locked_accounts"], 1)
