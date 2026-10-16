from django.core.exceptions import PermissionDenied, ValidationError
from django.template import Context, Template
from django.test import TestCase, override_settings
from django.urls import reverse

from cases.tests import PW, make_user

from . import services
from .models import Notification

FAST = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


@FAST
class NotificationServiceTests(TestCase):
    def setUp(self):
        self.a = make_user("alice")
        self.b = make_user("bob")

    def test_notify_creates_an_unread_notification(self):
        n = services.notify(self.a, "test", "Hello", "Body text", "/laboratory/mine/")
        self.assertEqual((n.recipient, n.title, n.url), (self.a, "Hello", "/laboratory/mine/"))
        self.assertFalse(n.is_read)

    def test_title_is_required_and_long_text_is_cut(self):
        with self.assertRaises(ValidationError):
            services.notify(self.a, "test", "   ")
        n = services.notify(self.a, "test", "t" * 500, "b" * 900)
        self.assertEqual((len(n.title), len(n.body)), (120, 300))

    def test_links_to_other_sites_are_refused(self):
        for bad in ("https://evil.example/x", "//evil.example/x", "javascript:alert(1)", "/ok\\evil", "/a\nb", "x" * 201):
            with self.assertRaises(ValidationError, msg=bad):
                services.notify(self.a, "test", "Hi", url=bad)
        self.assertEqual(Notification.objects.count(), 0)
        self.assertEqual(services.notify(self.a, "test", "Hi").url, "")

    def test_inactive_account_gets_nothing(self):
        self.b.is_active = False
        self.b.save()
        self.assertIsNone(services.notify(self.b, "test", "Hi"))
        self.assertEqual(Notification.objects.count(), 0)

    def test_notify_many_skips_duplicates(self):
        made = services.notify_many([self.a, self.a, self.b], "test", "Hi")
        self.assertEqual(len(made), 2)

    def test_only_the_owner_can_mark_read(self):
        n = services.notify(self.a, "test", "Hi")
        with self.assertRaises(PermissionDenied):
            services.mark_read(n, self.b)
        services.mark_read(n, self.a)
        first = n.read_at
        self.assertIsNotNone(first)
        services.mark_read(n, self.a)  # a second time changes nothing
        self.assertEqual(n.read_at, first)

    def test_mark_all_read_touches_only_own(self):
        services.notify(self.a, "test", "1")
        services.notify(self.a, "test", "2")
        services.notify(self.b, "test", "3")
        self.assertEqual(services.mark_all_read(self.a), 2)
        self.assertEqual(services.unread_count(self.a), 0)
        self.assertEqual(services.unread_count(self.b), 1)


@FAST
class NotificationViewTests(TestCase):
    def setUp(self):
        self.a = make_user("alice")
        self.b = make_user("bob")
        self.n = services.notify(self.a, "test", "Alice message", "private text", "/laboratory/mine/")

    def login(self, user):
        self.client.logout()
        self.assertTrue(self.client.login(username=user.username, password=PW))

    def test_list_shows_only_own(self):
        services.notify(self.b, "test", "Bob message")
        self.login(self.a)
        resp = self.client.get(reverse("notifications:list"))
        self.assertContains(resp, "Alice message")
        self.assertNotContains(resp, "Bob message")

    def test_open_marks_read_and_goes_to_the_link(self):
        self.login(self.a)
        resp = self.client.post(reverse("notifications:open", args=[self.n.pk]))
        self.assertRedirects(resp, "/laboratory/mine/", fetch_redirect_response=False)
        self.n.refresh_from_db()
        self.assertTrue(self.n.is_read)

    def test_open_without_a_link_returns_to_the_list(self):
        n = services.notify(self.a, "test", "No link")
        self.login(self.a)
        resp = self.client.post(reverse("notifications:open", args=[n.pk]))
        self.assertRedirects(resp, reverse("notifications:list"))

    def test_stored_bad_link_is_not_followed(self):
        Notification.objects.filter(pk=self.n.pk).update(url="https://evil.example/")
        self.login(self.a)
        resp = self.client.post(reverse("notifications:open", args=[self.n.pk]))
        self.assertRedirects(resp, reverse("notifications:list"))

    def test_someone_elses_notification_is_404_and_stays_unread(self):
        self.login(self.b)
        self.assertEqual(self.client.post(reverse("notifications:open", args=[self.n.pk])).status_code, 404)
        self.n.refresh_from_db()
        self.assertFalse(self.n.is_read)

    def test_open_needs_post(self):
        self.login(self.a)
        self.assertEqual(self.client.get(reverse("notifications:open", args=[self.n.pk])).status_code, 405)

    def test_mark_all_view(self):
        self.login(self.a)
        self.client.post(reverse("notifications:mark_all"))
        self.n.refresh_from_db()
        self.assertTrue(self.n.is_read)

    def test_anonymous_is_sent_to_login(self):
        resp = self.client.get(reverse("notifications:list"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("login", resp["Location"])


@FAST
class TemplateTagTests(TestCase):
    def test_unread_count_tag(self):
        a = make_user("alice")
        services.notify(a, "test", "1")
        n2 = services.notify(a, "test", "2")
        services.mark_read(n2, a)
        out = Template("{% load notification_tags %}{% unread_notifications as n %}{{ n }}").render(Context({"user": a}))
        self.assertEqual(out, "1")
