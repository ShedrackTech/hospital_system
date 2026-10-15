import datetime
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from cases.models import Case
from core.models import AuditLog
from departments.models import StaffProfile
from patients.models import Patient

from . import services
from .models import ChargeItem, Invoice, InvoiceLine, Payment

PW = "S3cret-pass-123"
FAST = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


def _required_values(model, skip):
    """Fill every required field of a model so tests do not depend on exact field lists."""
    values = {}
    for f in model._meta.concrete_fields:
        if f.primary_key or f.name in skip or f.has_default() or f.null or f.blank:
            continue
        if f.choices:
            values[f.name] = f.choices[0][0]
        elif f.get_internal_type() == "DateField":
            values[f.name] = datetime.date(1990, 1, 1)
        else:
            values[f.name] = "x"
    return values


_counter = [0]


def make_user(role="patient", category=None, **extra):
    _counter[0] += 1
    user = User.objects.create_user(username=f"u{_counter[0]}", password=PW, role=role, **extra)
    if category:
        StaffProfile.objects.create(user=user, category=category, job_title="Test", grade="junior")
    return user


def make_patient():
    user = make_user("patient", first_name="Pat", last_name="Ient")
    return Patient.objects.create(user=user, **_required_values(Patient, {"user"}))


def make_cashier():
    return make_user("staff", "admin")


def make_admin():
    return make_user("sub_admin")


def make_item(name="Consultation", price="5000.00", **kw):
    return ChargeItem.objects.create(name=name, unit_price=Decimal(price), **kw)


@FAST
class InvoiceServiceTests(TestCase):
    def setUp(self):
        self.cashier = make_cashier()
        self.patient = make_patient()
        self.item = make_item()
        self.item2 = make_item("X-ray", "12500.50", category="procedure")

    def test_create_invoice_totals_and_number(self):
        inv = services.create_invoice(self.patient, [(self.item, 2), (self.item2, 1)], self.cashier)
        self.assertEqual(inv.total, Decimal("22500.50"))
        self.assertEqual(inv.number, f"INV{inv.pk:06d}")
        self.assertEqual(inv.status, Invoice.Status.OPEN)
        self.assertEqual(inv.lines.count(), 2)
        self.assertTrue(AuditLog.objects.filter(action="invoice_created", patient=self.patient).exists())

    def test_same_item_twice_is_added_together(self):
        inv = services.create_invoice(self.patient, [(self.item, 1), (self.item, 2)], self.cashier)
        self.assertEqual(inv.lines.count(), 1)
        self.assertEqual(inv.lines.get().quantity, 3)

    def test_price_change_does_not_change_old_invoice(self):
        inv = services.create_invoice(self.patient, [(self.item, 1)], self.cashier)
        self.item.unit_price = Decimal("9999.00")
        self.item.save()
        line = InvoiceLine.objects.get(invoice=inv)
        self.assertEqual(line.unit_price, Decimal("5000.00"))
        self.assertEqual(line.description, "Consultation")

    def test_rejects_empty_inactive_and_bad_quantity(self):
        with self.assertRaises(ValidationError):
            services.create_invoice(self.patient, [], self.cashier)
        self.item.is_active = False
        self.item.save()
        with self.assertRaises(ValidationError):
            services.create_invoice(self.patient, [(self.item, 1)], self.cashier)
        with self.assertRaises(ValidationError):
            services.create_invoice(self.patient, [(self.item2, 0)], self.cashier)
        with self.assertRaises(ValidationError):
            services.create_invoice(self.patient, [(self.item2, services.MAX_QUANTITY + 1)], self.cashier)
        self.assertEqual(Invoice.objects.count(), 0)

    def test_case_must_belong_to_the_patient(self):
        other = make_patient()
        case = Case.objects.create(patient=other, complaint="private complaint")
        with self.assertRaises(ValidationError):
            services.create_invoice(self.patient, [(self.item, 1)], self.cashier, case=case)

    def test_only_front_desk_creates_invoices(self):
        for user in (self.patient.user, make_user("doctor", "medical"), make_user("staff", "support")):
            with self.assertRaises(PermissionDenied):
                services.create_invoice(self.patient, [(self.item, 1)], user)
        # administrators may
        services.create_invoice(self.patient, [(self.item, 1)], make_admin())

    def test_inactive_patient_cannot_be_billed(self):
        self.patient.user.is_active = False
        self.patient.user.save()
        with self.assertRaises(ValidationError):
            services.create_invoice(self.patient, [(self.item, 1)], self.cashier)


@FAST
class PaymentServiceTests(TestCase):
    def setUp(self):
        self.cashier = make_cashier()
        self.patient = make_patient()
        self.item = make_item(price="1000.00")
        self.inv = services.create_invoice(self.patient, [(self.item, 3)], self.cashier)  # 3000

    def test_partial_then_full_payment(self):
        p1 = services.record_payment(self.inv, "1000", "cash", "", self.cashier)
        self.assertEqual(self.inv.amount_paid, Decimal("1000.00"))
        self.assertEqual(self.inv.status, Invoice.Status.OPEN)
        self.assertEqual(p1.receipt_number, f"RCT{p1.pk:06d}")
        services.record_payment(self.inv, "2000", "transfer", "TRX-77", self.cashier)
        self.assertEqual(self.inv.status, Invoice.Status.PAID)
        self.assertIsNotNone(self.inv.paid_at)
        self.assertEqual(self.inv.balance, Decimal("0.00"))
        self.assertEqual(AuditLog.objects.filter(action="payment_recorded").count(), 2)

    def test_overpayment_zero_and_bad_amount_rejected(self):
        for bad in ("3000.01", "0", "-5", "abc"):
            with self.assertRaises(ValidationError):
                services.record_payment(self.inv, bad, "cash", "", self.cashier)
        self.assertEqual(Payment.objects.count(), 0)

    def test_transfer_and_pos_need_a_reference(self):
        for method in ("transfer", "pos"):
            with self.assertRaises(ValidationError):
                services.record_payment(self.inv, "100", method, "", self.cashier)
        with self.assertRaises(ValidationError):
            services.record_payment(self.inv, "100", "crypto", "x", self.cashier)

    def test_paid_invoice_takes_no_more_money(self):
        services.record_payment(self.inv, "3000", "cash", "", self.cashier)
        with self.assertRaises(ValidationError):
            services.record_payment(self.inv, "1", "cash", "", self.cashier)

    def test_patient_and_other_staff_cannot_record_payments(self):
        for user in (self.patient.user, make_user("doctor", "medical"), make_user("staff", "support")):
            with self.assertRaises(PermissionDenied):
                services.record_payment(self.inv, "100", "cash", "", user)

    def test_database_blocks_overpaying(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Invoice.objects.filter(pk=self.inv.pk).update(amount_paid=Decimal("3000.01"))


@FAST
class VoidTests(TestCase):
    def setUp(self):
        self.cashier = make_cashier()
        self.admin = make_admin()
        self.patient = make_patient()
        self.inv = services.create_invoice(self.patient, [(make_item(), 1)], self.cashier)

    def test_front_desk_cannot_void(self):
        with self.assertRaises(PermissionDenied):
            services.void_invoice(self.inv, self.cashier, "mistake")

    def test_admin_voids_with_reason_only(self):
        with self.assertRaises(ValidationError):
            services.void_invoice(self.inv, self.admin, "  ")
        services.void_invoice(self.inv, self.admin, "Billed to the wrong patient")
        self.assertEqual(self.inv.status, Invoice.Status.VOID)
        self.assertEqual(self.inv.voided_by, self.admin)
        self.assertTrue(AuditLog.objects.filter(action="invoice_voided").exists())

    def test_void_invoice_takes_no_payment_and_cannot_void_twice(self):
        services.void_invoice(self.inv, self.admin, "mistake")
        with self.assertRaises(ValidationError):
            services.record_payment(self.inv, "100", "cash", "", self.cashier)
        with self.assertRaises(ValidationError):
            services.void_invoice(self.inv, self.admin, "again")

    def test_invoice_with_payment_cannot_be_voided(self):
        services.record_payment(self.inv, "100", "cash", "", self.cashier)
        with self.assertRaises(ValidationError):
            services.void_invoice(self.inv, self.admin, "too late")


@FAST
class ViewAccessTests(TestCase):
    def setUp(self):
        self.cashier = make_cashier()
        self.admin = make_admin()
        self.patient = make_patient()
        self.other = make_patient()
        self.item = make_item(price="2500.00")
        self.case = Case.objects.create(patient=self.patient, complaint="SECRET-COMPLAINT-TEXT")
        self.inv = services.create_invoice(self.patient, [(self.item, 2)], self.cashier, case=self.case)

    def login(self, user):
        self.client.login(username=user.username, password=PW)

    def test_patient_sees_only_own_invoices(self):
        self.login(self.patient.user)
        self.assertContains(self.client.get(reverse("billing:mine")), self.inv.number)
        self.assertEqual(self.client.get(reverse("billing:detail", args=[self.inv.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("billing:print", args=[self.inv.pk])).status_code, 200)
        self.client.logout()
        self.login(self.other.user)
        self.assertNotContains(self.client.get(reverse("billing:mine")), self.inv.number)
        self.assertEqual(self.client.get(reverse("billing:detail", args=[self.inv.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("billing:print", args=[self.inv.pk])).status_code, 404)

    def test_patient_cannot_reach_staff_pages_or_pay(self):
        self.login(self.patient.user)
        for name in ("billing:invoice_list", "billing:new", "billing:items", "billing:item_new"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)
        resp = self.client.post(reverse("billing:pay", args=[self.inv.pk]), {"amount": "100", "method": "cash"})
        self.assertEqual(resp.status_code, 403)
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.amount_paid, 0)

    def test_medical_and_support_staff_see_no_billing(self):
        for user in (make_user("doctor", "medical"), make_user("staff", "support")):
            self.login(user)
            self.assertEqual(self.client.get(reverse("billing:invoice_list")).status_code, 403)
            self.assertEqual(self.client.get(reverse("billing:detail", args=[self.inv.pk])).status_code, 404)
            self.assertEqual(self.client.get(reverse("billing:home")).status_code, 403)
            self.client.logout()

    def test_front_desk_sees_invoice_but_not_the_complaint(self):
        self.login(self.cashier)
        resp = self.client.get(reverse("billing:detail", args=[self.inv.pk]))
        self.assertContains(resp, self.inv.number)
        self.assertContains(resp, f"Case #{self.case.pk}")
        self.assertNotContains(resp, "SECRET-COMPLAINT-TEXT")
        new = self.client.get(reverse("billing:new"), {"patient": self.patient.user.login_id})
        self.assertNotContains(new, "SECRET-COMPLAINT-TEXT")
        self.assertTrue(AuditLog.objects.filter(action="invoice_viewed", actor=self.cashier).exists())

    def test_own_view_by_patient_is_not_audited_but_staff_print_is(self):
        self.login(self.patient.user)
        self.client.get(reverse("billing:detail", args=[self.inv.pk]))
        self.assertFalse(AuditLog.objects.filter(action="invoice_viewed").exists())
        self.client.logout()
        self.login(self.cashier)
        self.client.get(reverse("billing:print", args=[self.inv.pk]))
        self.assertTrue(AuditLog.objects.filter(action="invoice_printed").exists())

    def test_create_invoice_through_the_page(self):
        self.login(self.cashier)
        data = {
            "patient": self.patient.user.login_id, "case": "", "note": "walk-in",
            "lines-TOTAL_FORMS": "3", "lines-INITIAL_FORMS": "0",
            "lines-MIN_NUM_FORMS": "0", "lines-MAX_NUM_FORMS": "20",
            "lines-0-item": str(self.item.pk), "lines-0-quantity": "",
            "lines-1-item": "", "lines-1-quantity": "",
            "lines-2-item": "", "lines-2-quantity": "",
        }
        resp = self.client.post(reverse("billing:new"), data)
        invoice = Invoice.objects.exclude(pk=self.inv.pk).get()
        self.assertRedirects(resp, reverse("billing:detail", args=[invoice.pk]))
        self.assertEqual(invoice.total, Decimal("2500.00"))  # empty quantity means 1

    def test_page_rejects_a_quantity_without_an_item(self):
        self.login(self.cashier)
        data = {
            "patient": self.patient.user.login_id, "case": "", "note": "",
            "lines-TOTAL_FORMS": "1", "lines-INITIAL_FORMS": "0",
            "lines-MIN_NUM_FORMS": "0", "lines-MAX_NUM_FORMS": "20",
            "lines-0-item": "", "lines-0-quantity": "4",
        }
        resp = self.client.post(reverse("billing:new"), data)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Invoice.objects.count(), 1)

    def test_unknown_card_number_shows_no_form(self):
        self.login(self.cashier)
        resp = self.client.get(reverse("billing:new"), {"patient": "PAT999999"})
        self.assertNotContains(resp, "Create invoice")

    def test_pay_through_the_page(self):
        self.login(self.cashier)
        self.client.post(reverse("billing:pay", args=[self.inv.pk]), {"amount": "5000", "method": "cash"})
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.status, Invoice.Status.PAID)

    def test_void_through_the_page_needs_an_admin(self):
        self.login(self.cashier)
        self.assertEqual(
            self.client.post(reverse("billing:void", args=[self.inv.pk]), {"reason": "x"}).status_code, 403
        )
        self.client.logout()
        self.login(self.admin)
        self.client.post(reverse("billing:void", args=[self.inv.pk]), {"reason": "wrong patient"})
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.status, Invoice.Status.VOID)

    def test_list_filters_and_audit(self):
        self.login(self.cashier)
        resp = self.client.get(reverse("billing:invoice_list"), {"q": self.patient.user.login_id})
        self.assertContains(resp, self.inv.number)
        resp = self.client.get(reverse("billing:invoice_list"), {"status": "paid"})
        self.assertNotContains(resp, self.inv.number)
        self.assertTrue(AuditLog.objects.filter(action="invoice_list_viewed").exists())

    def test_price_list_front_desk_reads_admin_edits(self):
        self.login(self.cashier)
        self.assertEqual(self.client.get(reverse("billing:items")).status_code, 200)
        self.assertEqual(self.client.get(reverse("billing:item_new")).status_code, 403)
        self.assertEqual(self.client.get(reverse("billing:item_edit", args=[self.item.pk])).status_code, 403)
        self.client.logout()
        self.login(self.admin)
        resp = self.client.post(
            reverse("billing:item_new"), {"name": "Dressing", "category": "procedure", "unit_price": "1500", "is_active": "on"}
        )
        self.assertRedirects(resp, reverse("billing:items"))
        self.assertTrue(ChargeItem.objects.filter(name="Dressing").exists())
        self.assertTrue(AuditLog.objects.filter(action="charge_item_created").exists())
        self.client.post(
            reverse("billing:item_edit", args=[self.item.pk]),
            {"name": "Consultation", "category": "consultation", "unit_price": "6000", "is_active": "on"},
        )
        self.assertTrue(AuditLog.objects.filter(action="charge_item_updated").exists())

    def test_home_redirects_by_role(self):
        self.login(self.patient.user)
        self.assertRedirects(self.client.get(reverse("billing:home")), reverse("billing:mine"))
        self.client.logout()
        self.login(self.cashier)
        self.assertRedirects(self.client.get(reverse("billing:home")), reverse("billing:invoice_list"))

    def test_anonymous_is_sent_to_login(self):
        resp = self.client.get(reverse("billing:detail", args=[self.inv.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("login", resp["Location"])
