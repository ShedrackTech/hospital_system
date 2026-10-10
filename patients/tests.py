from datetime import date

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from django.urls import reverse

from .cards import add_months, issue_card
from .models import Allergy, CardRenewal, CardType, Family, Patient
from .security import CAPTCHA_SESSION_KEY

User = get_user_model()

PASSWORD = "Str0ngPass!2026"


def registration_data(**overrides):
    data = {
        "first_name": "Ada",
        "last_name": "Obi",
        "username": "ada",
        "email": "",
        "phone": "08031234567",
        "date_of_birth": "1990-05-01",
        "gender": "female",
        "address": "Nsukka",
        "complaint": "Headache",
        "blood_group": "",
        "emergency_contact_name": "",
        "emergency_contact_phone": "",
        "password1": PASSWORD,
        "password2": PASSWORD,
        "card_choice": "single",
    }
    data.update(overrides)
    return data


def public_register(client, follow=False, captcha_offset=0, **overrides):
    """
    Open the public form (which creates a captcha), answer it, and submit.
    Use captcha_offset=1 to submit a wrong answer on purpose.
    """
    client.get(reverse("patients:register"))
    data = registration_data(**overrides)
    data.setdefault("captcha", client.session[CAPTCHA_SESSION_KEY] + captcha_offset)
    return client.post(reverse("patients:register"), data, follow=follow)


def make_patient(username, first_name):
    user = User.objects.create_user(
        username, password=PASSWORD, role=User.Role.PATIENT, first_name=first_name
    )
    return Patient.objects.create(
        user=user, date_of_birth=date(1990, 1, 1), gender=Patient.Gender.MALE
    )


from departments.models import StaffProfile


class RegistrationTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_self_registration_creates_patient_with_card_number(self):
        response = public_register(self.client, follow=True)
        user = User.objects.get(first_name="Ada")
        self.assertEqual(user.role, User.Role.PATIENT)
        self.assertTrue(user.login_id.startswith("PAT"))
        self.assertEqual(user.username, "ada")
        self.assertFalse(user.is_staff)
        self.assertTrue(Patient.objects.filter(user=user).exists())
        self.assertContains(response, user.login_id)

    def test_card_number_is_shown_only_once(self):
        public_register(self.client)
        first = self.client.get(reverse("patients:registered"))
        self.assertEqual(first.status_code, 200)
        second = self.client.get(reverse("patients:registered"))
        self.assertEqual(second.status_code, 302)

    def test_new_patient_can_log_in_with_card_number(self):
        public_register(self.client)
        card = User.objects.get(first_name="Ada").login_id
        self.client.logout()
        self.assertTrue(self.client.login(username=card, password=PASSWORD))
        self.client.logout()
        self.assertTrue(self.client.login(username="ada", password=PASSWORD))
        self.client.logout()
        self.assertTrue(self.client.login(username="ADA", password=PASSWORD))

    def test_duplicate_username_is_rejected_ignoring_case(self):
        public_register(self.client)
        self.client.logout()
        response = public_register(self.client, first_name="Bola", username="ADA")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.filter(role="patient").count(), 1)

    def test_reserved_and_invalid_usernames_are_rejected(self):
        for bad in ("PAT000123", "stf9", "a b", "ab", "bad/name"):
            response = public_register(self.client, username=bad)
            self.assertEqual(response.status_code, 200, bad)
        self.assertFalse(User.objects.filter(role="patient").exists())

    def test_password_mismatch_creates_nothing(self):
        response = public_register(self.client, password2="different")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(first_name="Ada").exists())

    def test_weak_password_is_rejected(self):
        response = public_register(self.client, password1="12345678", password2="12345678")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(first_name="Ada").exists())

    def test_future_date_of_birth_is_rejected(self):
        response = public_register(self.client, date_of_birth="2999-01-01")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(first_name="Ada").exists())

    def test_two_registrations_get_different_card_numbers(self):
        public_register(self.client)
        self.client.logout()
        public_register(self.client, first_name="Bola", username="bola")
        ids = set(User.objects.filter(role="patient").values_list("login_id", flat=True))
        self.assertEqual(len(ids), 2)

    def test_logged_in_users_are_redirected_from_public_form(self):
        patient = make_patient("p1", "Chi")
        self.client.force_login(patient.user)
        response = self.client.get(reverse("patients:register"))
        self.assertEqual(response.status_code, 302)

    def test_wrong_captcha_is_rejected(self):
        response = public_register(self.client, captcha_offset=1)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(first_name="Ada").exists())

    def test_missing_captcha_is_rejected(self):
        data = registration_data()
        response = self.client.post(reverse("patients:register"), data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(first_name="Ada").exists())

    def test_captcha_answer_cannot_be_reused(self):
        self.client.get(reverse("patients:register"))
        answer = self.client.session[CAPTCHA_SESSION_KEY]
        # First submit has a form error, which uses up the answer
        self.client.post(
            reverse("patients:register"),
            registration_data(password2="different", captcha=answer),
        )
        # A new question was created. Make sure its answer differs from the old one.
        session = self.client.session
        session[CAPTCHA_SESSION_KEY] = answer + 1000
        session.save()
        # Re-sending the old answer with valid data must fail
        response = self.client.post(
            reverse("patients:register"), registration_data(captcha=answer)
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(first_name="Ada").exists())

    def test_filled_honeypot_is_rejected(self):
        response = public_register(self.client, website="http://spam.example")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(first_name="Ada").exists())

    @override_settings(REGISTRATION_RATE_LIMIT=2)
    def test_too_many_attempts_are_blocked(self):
        for _ in range(2):
            response = public_register(self.client, captcha_offset=1)  # wrong on purpose
            self.assertEqual(response.status_code, 200)
        blocked = public_register(self.client)  # a valid attempt, but over the limit
        self.assertEqual(blocked.status_code, 429)
        self.assertFalse(User.objects.filter(first_name="Ada").exists())


class StaffRegistrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.nurse = User.objects.create_user(
            "nurse1", password=PASSWORD, role=User.Role.NURSE
        )
        StaffProfile.objects.get_or_create(
            user=cls.nurse,
            defaults={"category": "admin", "job_title": "Receptionist"},
        )
        cls.patient = make_patient("p1", "Chi")

    def test_anonymous_is_sent_to_login(self):
        response = self.client.get(reverse("patients:staff_register"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_staff_can_register_a_patient(self):
        self.client.force_login(self.nurse)
        response = self.client.post(
            reverse("patients:staff_register"), registration_data(first_name="Dayo", username="dayo")
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(first_name="Dayo", username="dayo", role="patient").exists())

    def test_staff_registration_shows_a_success_page(self):
        self.client.force_login(self.nurse)
        response = self.client.post(
            reverse("patients:staff_register"),
            registration_data(first_name="Dayo", username="dayo"),
            follow=True,
        )
        user = User.objects.get(first_name="Dayo", username="dayo")
        self.assertContains(response, "Patient registered successfully")
        self.assertContains(response, "Dayo Obi")
        self.assertContains(response, user.login_id)

    def test_staff_form_shows_an_error_summary(self):
        self.client.force_login(self.nurse)
        response = self.client.post(
            reverse("patients:staff_register"),
            registration_data(first_name="Dayo", username="dayo", password2="different"),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please correct the errors below")
        self.assertContains(response, "do not match")
        self.assertFalse(User.objects.filter(first_name="Dayo", username="dayo").exists())

    def test_patient_cannot_use_staff_registration(self):
        self.client.force_login(self.patient.user)
        response = self.client.get(reverse("patients:staff_register"))
        self.assertEqual(response.status_code, 403)


class PatientRecordAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.sub_admin = User.objects.create_user(
            "subadmin", password=PASSWORD, role=User.Role.SUB_ADMIN
        )
        cls.nurse = User.objects.create_user(
            "nurse1", password=PASSWORD, role=User.Role.NURSE
        )
        StaffProfile.objects.get_or_create(
            user=cls.nurse,
            defaults={"category": "admin", "job_title": "Receptionist"},
        )
        cls.alice = make_patient("alice", "Alice")
        cls.bob = make_patient("bob", "Bob")
        Allergy.objects.create(patient=cls.alice, name="Penicillin", severity="severe")

    def test_admin_can_list_search_and_view(self):
        self.client.force_login(self.sub_admin)
        listing = self.client.get(reverse("patients:list"))
        self.assertContains(listing, "Alice")
        self.assertContains(listing, "Bob")
        search = self.client.get(reverse("patients:list"), {"q": self.alice.card_number})
        self.assertContains(search, "Alice")
        self.assertNotContains(search, "Bob")
        detail = self.client.get(reverse("patients:detail", args=[self.alice.pk]))
        self.assertContains(detail, "Penicillin")

    def test_nurse_cannot_list_or_view_patients(self):
        self.client.force_login(self.nurse)
        self.assertEqual(self.client.get(reverse("patients:list")).status_code, 403)
        detail = self.client.get(reverse("patients:detail", args=[self.alice.pk]))
        self.assertEqual(detail.status_code, 403)

    def test_patient_cannot_view_the_patient_list_or_other_records(self):
        self.client.force_login(self.alice.user)
        self.assertEqual(self.client.get(reverse("patients:list")).status_code, 403)
        other = self.client.get(reverse("patients:detail", args=[self.bob.pk]))
        self.assertEqual(other.status_code, 403)

    def test_my_profile_shows_only_own_data(self):
        self.client.force_login(self.alice.user)
        response = self.client.get(reverse("patients:my_profile"))
        self.assertContains(response, "Alice")
        self.assertContains(response, "Penicillin")
        self.assertNotContains(response, "Bob")
        self.assertNotContains(response, self.bob.card_number)

    def test_staff_cannot_use_my_profile(self):
        self.client.force_login(self.nurse)
        response = self.client.get(reverse("patients:my_profile"))
        self.assertEqual(response.status_code, 403)


class PatientAdminTests(TestCase):
    def test_admin_pages_load(self):
        root = User.objects.create_superuser("root", password=PASSWORD)
        patient = make_patient("alice", "Alice")
        family = Family.objects.create(name="Alice family")
        patient.family = family
        patient.relationship = Patient.Relationship.HEAD
        patient.save()
        self.client.force_login(root)
        for url in (
            reverse("admin:patients_patient_changelist"),
            reverse("admin:patients_patient_change", args=[patient.pk]),
            reverse("admin:patients_family_changelist"),
            reverse("admin:patients_family_add"),
            reverse("admin:patients_family_change", args=[family.pk]),
        ):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_admin_add_patient_goes_to_the_registration_form(self):
        root = User.objects.create_superuser("root", password=PASSWORD)
        self.client.force_login(root)
        response = self.client.get(reverse("admin:patients_patient_add"))
        self.assertRedirects(response, reverse("patients:staff_register"))


class FamilyCardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.sub_admin = User.objects.create_user(
            "subadmin", password=PASSWORD, role=User.Role.SUB_ADMIN
        )
        cls.nurse = User.objects.create_user(
            "nurse1", password=PASSWORD, role=User.Role.NURSE
        )
        StaffProfile.objects.get_or_create(
            user=cls.nurse,
            defaults={"category": "admin", "job_title": "Receptionist"},
        )

    def register(self, **overrides):
        return self.client.post(
            reverse("patients:staff_register"), registration_data(**overrides)
        )

    def make_family(self):
        self.client.force_login(self.nurse)
        self.register(card_choice="new_family", address="12 Zik Avenue")
        return Family.objects.get()

    def test_new_family_card_makes_the_patient_the_head(self):
        self.client.force_login(self.nurse)
        response = self.client.post(
            reverse("patients:staff_register"),
            registration_data(card_choice="new_family", address="12 Zik Avenue"),
            follow=True,
        )
        ada = Patient.objects.get(user__username="ada")
        family = ada.family
        self.assertTrue(family.family_number.startswith("FAM"))
        self.assertEqual(family.name, "Obi family")
        self.assertEqual(family.address, "12 Zik Avenue")
        self.assertEqual(ada.relationship, Patient.Relationship.HEAD)
        self.assertEqual(family.head, ada)
        self.assertContains(response, family.family_number)

    def test_members_keep_their_own_cards_and_logins(self):
        family = self.make_family()
        response = self.register(
            first_name="Bola",
            username="bola",
            card_choice="join",
            family_number=family.family_number.lower(),
            relationship="child",
        )
        self.assertEqual(response.status_code, 302)
        ada = Patient.objects.get(user__username="ada")
        bola = Patient.objects.get(user__username="bola")
        self.assertEqual(bola.family, family)
        self.assertEqual(bola.relationship, "child")
        self.assertNotEqual(ada.card_number, bola.card_number)
        self.client.logout()
        self.assertTrue(self.client.login(username="bola", password=PASSWORD))
        self.client.logout()
        self.assertTrue(self.client.login(username=ada.card_number, password=PASSWORD))

    def test_single_card_leaves_the_patient_ungrouped(self):
        self.client.force_login(self.nurse)
        self.register(card_choice="single")
        self.assertIsNone(Patient.objects.get(user__username="ada").family)

    def test_joining_needs_a_real_family_number_and_a_relationship(self):
        family = self.make_family()
        bad_attempts = [
            dict(card_choice="join", family_number="", relationship="child"),
            dict(card_choice="join", family_number="FAM999999", relationship="child"),
            dict(card_choice="join", family_number=family.family_number, relationship=""),
            dict(card_choice="join", family_number=family.family_number, relationship="head"),
        ]
        for attempt in bad_attempts:
            response = self.register(first_name="Bola", username="bola", **attempt)
            self.assertEqual(response.status_code, 200, attempt)
        self.assertFalse(User.objects.filter(username="bola").exists())

    def test_public_registration_has_no_family_options(self):
        response = self.client.get(reverse("patients:register"))
        self.assertNotContains(response, "card_choice")

    def test_add_family_member_link_prefills_the_form(self):
        family = self.make_family()
        response = self.client.get(
            reverse("patients:staff_register"), {"family": family.family_number}
        )
        initial = response.context["form"].initial
        self.assertEqual(initial["card_choice"], "join")
        self.assertEqual(initial["family_number"], family.family_number)
        self.assertEqual(initial["address"], "12 Zik Avenue")

    def test_a_family_can_have_only_one_head(self):
        family = Family.objects.create(name="Obi family")
        first = make_patient("first", "First")
        second = make_patient("second", "Second")
        first.family, first.relationship = family, Patient.Relationship.HEAD
        first.save()
        second.family, second.relationship = family, Patient.Relationship.HEAD
        with self.assertRaises(IntegrityError), transaction.atomic():
            second.save()

    def test_relationship_needs_a_family(self):
        patient = make_patient("solo", "Solo")
        patient.relationship = Patient.Relationship.CHILD
        with self.assertRaises(ValidationError):
            patient.clean()

    def test_admin_can_list_search_and_view_families(self):
        family = self.make_family()
        ada = Patient.objects.get(user__username="ada")
        Allergy.objects.create(patient=ada, name="Penicillin", severity="severe")
        self.client.force_login(self.sub_admin)
        listing = self.client.get(reverse("patients:family_list"), {"q": ada.card_number})
        self.assertContains(listing, family.family_number)
        detail = self.client.get(reverse("patients:family_detail", args=[family.pk]))
        self.assertContains(detail, ada.card_number)
        self.assertContains(detail, "Head of family")
        # The family page groups people. It never shows medical details.
        self.assertNotContains(detail, "Penicillin")

    def test_patient_search_finds_members_by_family_number(self):
        family = self.make_family()
        self.register(
            first_name="Bola",
            username="bola",
            card_choice="join",
            family_number=family.family_number,
            relationship="child",
        )
        self.client.force_login(self.sub_admin)
        response = self.client.get(
            reverse("patients:list"), {"q": family.family_number}
        )
        self.assertContains(response, "Ada Obi")
        self.assertContains(response, "Bola Obi")

    def test_only_admins_can_use_family_pages(self):
        family = self.make_family()
        patient = Patient.objects.get(user__username="ada")
        urls = [
            reverse("patients:family_list"),
            reverse("patients:family_detail", args=[family.pk]),
        ]
        for user in (self.nurse, patient.user):
            self.client.force_login(user)
            for url in urls:
                self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_my_profile_shows_the_family_number_but_not_other_members(self):
        family = self.make_family()
        self.register(
            first_name="Bola",
            username="bola",
            card_choice="join",
            family_number=family.family_number,
            relationship="child",
        )
        ada = Patient.objects.get(user__username="ada")
        bola = Patient.objects.get(user__username="bola")
        self.client.force_login(ada.user)
        response = self.client.get(reverse("patients:my_profile"))
        self.assertContains(response, family.family_number)
        self.assertNotContains(response, "Bola")
        self.assertNotContains(response, bola.card_number)


class CardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.sub_admin = User.objects.create_user(
            "subadmin", password=PASSWORD, role=User.Role.SUB_ADMIN
        )
        cls.nurse = User.objects.create_user(
            "nurse1", password=PASSWORD, role=User.Role.NURSE
        )
        StaffProfile.objects.get_or_create(
            user=cls.nurse,
            defaults={"category": "admin", "job_title": "Receptionist"},
        )
        cls.single = CardType.for_kind(CardType.Kind.SINGLE)
        cls.family_type = CardType.for_kind(CardType.Kind.FAMILY)

    def set_fees(self, single, family):
        CardType.objects.filter(kind="single").update(fee=single)
        CardType.objects.filter(kind="family").update(fee=family)

    def register(self, **overrides):
        return self.client.post(
            reverse("patients:staff_register"), registration_data(**overrides)
        )

    # ---- dates
    def test_add_months(self):
        from datetime import date
        self.assertEqual(add_months(date(2026, 10, 7), 6), date(2027, 4, 7))
        self.assertEqual(add_months(date(2026, 10, 7), 12), date(2027, 10, 7))
        self.assertEqual(add_months(date(2026, 8, 31), 6), date(2027, 2, 28))
        self.assertEqual(add_months(date(2027, 8, 31), 6), date(2028, 2, 29))

    def test_default_validity_is_six_months_single_and_twelve_months_family(self):
        self.assertEqual(self.single.validity_months, 6)
        self.assertEqual(self.family_type.validity_months, 12)

    # ---- issuing at registration
    def test_single_card_at_registration(self):
        self.set_fees(2000, 5000)
        self.client.force_login(self.nurse)
        response = self.register(fee_received="on")
        self.assertEqual(response.status_code, 302)
        patient = Patient.objects.get(user__username="ada")
        renewal = patient.latest_card_renewal
        today = timezone.localdate()
        self.assertEqual(renewal.expires_on, add_months(today, 6))
        self.assertEqual(renewal.amount_charged, 2000)
        self.assertEqual(renewal.received_by, self.nurse)
        self.assertTrue(patient.has_valid_card)

    def test_new_family_card_at_registration_lasts_a_year(self):
        self.set_fees(2000, 5000)
        self.client.force_login(self.nurse)
        self.register(card_choice="new_family", fee_received="on")
        patient = Patient.objects.get(user__username="ada")
        renewal = patient.latest_card_renewal
        self.assertEqual(renewal.family, patient.family)
        self.assertEqual(renewal.expires_on, add_months(timezone.localdate(), 12))
        self.assertEqual(renewal.amount_charged, 5000)

    def test_the_fee_must_be_confirmed_as_received(self):
        self.set_fees(2000, 5000)
        self.client.force_login(self.nurse)
        for choice in ("single", "new_family"):
            response = self.register(card_choice=choice)
            self.assertEqual(response.status_code, 200, choice)
            self.assertContains(response, "has been received")
        self.assertFalse(User.objects.filter(username="ada").exists())
        self.assertEqual(CardRenewal.objects.count(), 0)

    def test_joining_a_family_charges_nothing_and_is_covered_by_the_family_card(self):
        self.set_fees(2000, 5000)
        self.client.force_login(self.nurse)
        self.register(card_choice="new_family", fee_received="on")
        family = Family.objects.get()
        self.register(
            first_name="Bola",
            username="bola",
            card_choice="join",
            family_number=family.family_number,
            relationship="child",
        )
        bola = Patient.objects.get(user__username="bola")
        self.assertEqual(CardRenewal.objects.count(), 1)  # only the family card was paid for
        self.assertTrue(bola.has_valid_card)
        self.assertEqual(bola.card_expires_on, family.card_expires_on)

    def test_single_card_covers_only_its_owner(self):
        alice = make_patient("alice", "Alice")
        bob = make_patient("bob", "Bob")
        issue_card(alice)
        self.assertTrue(alice.has_valid_card)
        self.assertFalse(bob.has_valid_card)
        self.assertEqual(bob.card_status, "none")

    def test_family_card_covers_every_member(self):
        family = Family.objects.create(name="Obi family")
        members = [make_patient(f"m{i}", f"M{i}") for i in range(3)]
        for member in members:
            member.family = family
            member.save()
        self.assertFalse(any(m.has_valid_card for m in members))
        issue_card(family)
        for member in members:
            self.assertTrue(Patient.objects.get(pk=member.pk).has_valid_card)

    def test_a_family_member_cannot_get_a_single_card(self):
        family = Family.objects.create(name="Obi family")
        member = make_patient("m1", "M1")
        member.family = family
        member.save()
        with self.assertRaises(ValueError):
            issue_card(member)

    # ---- expiry and renewal
    def test_card_expires_after_its_period(self):
        from datetime import timedelta
        patient = make_patient("alice", "Alice")
        long_ago = timezone.localdate() - timedelta(days=400)
        issue_card(patient, today=long_ago)
        self.assertEqual(patient.card_status, "expired")
        self.assertFalse(patient.has_valid_card)

    def test_renewing_an_expired_card_starts_today(self):
        from datetime import timedelta
        patient = make_patient("alice", "Alice")
        issue_card(patient, today=timezone.localdate() - timedelta(days=400))
        renewal = issue_card(patient)
        today = timezone.localdate()
        self.assertEqual(renewal.starts_on, today)
        self.assertEqual(renewal.expires_on, add_months(today, 6))
        self.assertTrue(patient.has_valid_card)

    def test_renewing_early_extends_from_the_expiry_date(self):
        patient = make_patient("alice", "Alice")
        first = issue_card(patient)
        second = issue_card(patient)
        self.assertEqual(second.starts_on, first.expires_on)
        self.assertEqual(second.expires_on, add_months(first.expires_on, 6))

    def test_old_fee_is_kept_when_prices_change(self):
        patient = make_patient("alice", "Alice")
        self.set_fees(1000, 3000)
        first = issue_card(patient)
        self.set_fees(2000, 5000)
        issue_card(patient)
        first.refresh_from_db()
        self.assertEqual(first.amount_charged, 1000)

    # ---- card desk
    def test_card_desk_finds_patients_and_families(self):
        patient = make_patient("alice", "Alice")
        family = Family.objects.create(name="Obi family")
        self.client.force_login(self.nurse)
        by_patient = self.client.get(reverse("patients:card_desk"), {"number": patient.card_number})
        self.assertContains(by_patient, "Single card")
        by_family = self.client.get(reverse("patients:card_desk"), {"number": family.family_number})
        self.assertContains(by_family, "Obi family")
        missing = self.client.get(reverse("patients:card_desk"), {"number": "PAT999999"})
        self.assertContains(missing, "No patient or family card found")

    def test_card_desk_issues_a_single_card(self):
        self.set_fees(2000, 5000)
        patient = make_patient("alice", "Alice")
        self.client.force_login(self.nurse)
        url = reverse("patients:card_desk")
        data = {"number": patient.card_number, "action": "renew"}
        self.client.post(url, data)  # fee not confirmed
        self.assertEqual(CardRenewal.objects.count(), 0)
        self.client.post(url, {**data, "fee_received": "on"})
        self.assertEqual(CardRenewal.objects.count(), 1)
        self.assertTrue(Patient.objects.get(pk=patient.pk).has_valid_card)

    def test_card_desk_renews_the_family_card_for_a_member(self):
        patient = make_patient("alice", "Alice")
        family = Family.objects.create(name="Obi family")
        patient.family = family
        patient.relationship = "head"
        patient.save()
        self.client.force_login(self.nurse)
        self.client.post(
            reverse("patients:card_desk"),
            {"number": patient.card_number, "action": "renew"},
        )
        renewal = CardRenewal.objects.get()
        self.assertEqual(renewal.family, family)
        self.assertIsNone(renewal.patient)

    def test_card_desk_upgrades_a_single_card_to_a_family_card(self):
        self.set_fees(2000, 5000)
        patient = make_patient("alice", "Alice")
        issue_card(patient)
        self.client.force_login(self.nurse)
        self.client.post(
            reverse("patients:card_desk"),
            {"number": patient.card_number, "action": "upgrade", "fee_received": "on"},
        )
        patient.refresh_from_db()
        self.assertIsNotNone(patient.family)
        self.assertEqual(patient.relationship, "head")
        self.assertEqual(patient.latest_card_renewal.family, patient.family)
        self.assertEqual(patient.latest_card_renewal.amount_charged, 5000)

    def test_a_family_member_cannot_be_upgraded_again(self):
        patient = make_patient("alice", "Alice")
        patient.family = Family.objects.create(name="Obi family")
        patient.save()
        self.client.force_login(self.nurse)
        self.client.post(
            reverse("patients:card_desk"),
            {"number": patient.card_number, "action": "upgrade"},
        )
        self.assertEqual(Family.objects.count(), 1)

    def test_patients_cannot_use_the_card_desk(self):
        patient = make_patient("alice", "Alice")
        self.client.force_login(patient.user)
        response = self.client.get(reverse("patients:card_desk"))
        self.assertEqual(response.status_code, 403)

    # ---- prices
    def test_admin_can_change_prices(self):
        self.client.force_login(self.sub_admin)
        url = reverse("patients:card_prices")
        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        formset = page.context["formset"]
        data = {
            "form-TOTAL_FORMS": "2",
            "form-INITIAL_FORMS": "2",
            "form-MIN_NUM_FORMS": "0",
            "form-MAX_NUM_FORMS": "1000",
        }
        fees = {"single": "2500.00", "family": "6000.00"}
        for i, form in enumerate(formset.forms):
            data[f"form-{i}-id"] = form.instance.pk
            data[f"form-{i}-fee"] = fees[form.instance.kind]
            data[f"form-{i}-validity_months"] = form.instance.validity_months
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(CardType.objects.get(kind="single").fee, 2500)
        self.assertEqual(CardType.objects.get(kind="family").fee, 6000)

    def test_family_card_cannot_cost_less_than_single(self):
        self.client.force_login(self.sub_admin)
        url = reverse("patients:card_prices")
        formset = self.client.get(url).context["formset"]
        data = {
            "form-TOTAL_FORMS": "2",
            "form-INITIAL_FORMS": "2",
            "form-MIN_NUM_FORMS": "0",
            "form-MAX_NUM_FORMS": "1000",
        }
        fees = {"single": "5000.00", "family": "2000.00"}
        for i, form in enumerate(formset.forms):
            data[f"form-{i}-id"] = form.instance.pk
            data[f"form-{i}-fee"] = fees[form.instance.kind]
            data[f"form-{i}-validity_months"] = form.instance.validity_months
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "at least as much")
        self.assertEqual(CardType.objects.get(kind="family").fee, 0)

    def test_only_admins_can_open_the_prices_page(self):
        self.client.force_login(self.nurse)
        self.assertEqual(self.client.get(reverse("patients:card_prices")).status_code, 403)

    # ---- pages
    def test_my_profile_shows_the_card_status(self):
        patient = make_patient("alice", "Alice")
        self.client.force_login(patient.user)
        self.assertContains(self.client.get(reverse("patients:my_profile")), "Not active")
        issue_card(patient)
        self.assertContains(self.client.get(reverse("patients:my_profile")), "Valid until")

    def test_public_registration_tells_the_patient_to_visit_the_front_desk(self):
        cache.clear()
        response = public_register(self.client, follow=True)
        self.assertContains(response, "front desk")
        self.assertFalse(Patient.objects.get(user__username="ada").has_valid_card)

    def test_registration_success_page_shows_the_card_and_fee(self):
        self.set_fees(2000, 5000)
        self.client.force_login(self.nurse)
        response = self.client.post(
            reverse("patients:staff_register"),
            registration_data(fee_received="on"),
            follow=True,
        )
        self.assertContains(response, "Single card")
        self.assertContains(response, "valid until")
        self.assertContains(response, "2000.00")

    def test_card_renewals_are_visible_read_only_in_admin(self):
        root = User.objects.create_superuser("root", password=PASSWORD)
        patient = make_patient("alice", "Alice")
        renewal = issue_card(patient)
        self.client.force_login(root)
        self.assertEqual(
            self.client.get(reverse("admin:patients_cardrenewal_changelist")).status_code, 200
        )
        self.assertEqual(
            self.client.get(reverse("admin:patients_cardrenewal_add")).status_code, 403
        )
        self.assertEqual(
            self.client.get(
                reverse("admin:patients_cardrenewal_change", args=[renewal.pk])
            ).status_code,
            200,
        )
