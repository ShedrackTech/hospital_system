from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from cases import services as case_services
from cases.tests import PW, make_patient, make_user
from core.models import AuditLog
from departments.forms import DepartmentForm
from departments.models import Department, StaffProfile
from patients.models import Allergy

from . import permissions as perms
from . import services
from .models import Dispensing, Drug, Prescription, PrescriptionItem, StockAdjustment, StockBatch

FAST = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


def staff(username, role, dept, category="medical", grade="junior"):
    user = make_user(username)
    user.role = role
    user.save()
    StaffProfile.objects.create(user=user, category=category, job_title="Staff",
                                department=dept, grade=grade)
    return user


def item(drug, quantity=10, **extra):
    data = {"drug": drug, "dose": "1 tablet", "frequency": "twice daily",
            "duration_days": 5, "quantity": quantity, "instructions": ""}
    data.update(extra)
    return data


def days(n):
    return timezone.localdate() + timedelta(days=n)


@FAST
class PharmacyBase(TestCase):
    def setUp(self):
        self.pharmacy = Department.objects.create(name="Pharmacy", is_pharmacy=True)
        self.surgery = Department.objects.create(name="Surgery")
        self.head = staff("head", "department_head", self.surgery, grade="senior")
        self.surgery.head = self.head
        self.surgery.save()
        self.doc = staff("doc", "doctor", self.surgery)
        self.other_doc = staff("otherdoc", "doctor", self.surgery)
        self.pharm = staff("pharm", "staff", self.pharmacy)
        self.senior_pharm = staff("seniorpharm", "senior_staff", self.pharmacy, grade="senior")
        self.pharm_head = staff("pharmhead", "department_head", self.pharmacy, grade="senior")
        self.pharmacy.head = self.pharm_head
        self.pharmacy.save()
        self.cleaner = staff("cleaner", "staff", None, category="support")
        self.admin = make_user("adminuser")
        self.admin.role = "sub_admin"
        self.admin.save()
        self.p1 = make_patient("pat1")
        self.p2 = make_patient("pat2")
        Allergy.objects.create(patient=self.p1, name="Penicillin", severity="severe")

        self.case = case_services.create_case(self.p1, "Fever")
        case_services.route_case(self.case, self.surgery, self.head)
        case_services.assign_case(self.case, self.doc, self.head)
        case_services.change_status(self.case, "in_treatment", self.doc)
        self.case.refresh_from_db()

        self.para = Drug.objects.create(name="Paracetamol", strength="500 mg", ingredients="paracetamol", unit="tablet")
        self.amox = Drug.objects.create(name="Amoxicillin", strength="500 mg", form="capsule",
                                        ingredients="amoxicillin, penicillin", unit="capsule")
        self.batch_late = StockBatch.objects.create(drug=self.para, batch_number="L2", expiry_date=days(400),
                                                    quantity_received=100, quantity_remaining=100)
        self.batch_early = StockBatch.objects.create(drug=self.para, batch_number="E1", expiry_date=days(100),
                                                     quantity_received=30, quantity_remaining=30)

    def login(self, username):
        self.client.logout()
        self.assertTrue(self.client.login(username=username, password=PW))

    def prescription(self, quantity=10):
        return services.prescribe(self.case, [item(self.para, quantity)], self.doc)


class PrescribingTests(PharmacyBase):
    def test_prescription_belongs_to_the_cases_patient(self):
        rx = self.prescription()
        self.assertEqual(rx.patient, self.p1)
        self.assertEqual(rx.status, "prescribed")
        self.assertEqual(rx.items.count(), 1)

    def test_empty_duplicate_inactive_and_pending_case_are_rejected(self):
        with self.assertRaises(ValidationError):
            services.prescribe(self.case, [], self.doc)
        with self.assertRaises(ValidationError):
            services.prescribe(self.case, [item(self.para), item(self.para)], self.doc)
        self.para.is_active = False
        self.para.save()
        with self.assertRaises(ValidationError):
            services.prescribe(self.case, [item(self.para)], self.doc)
        self.para.is_active = True
        self.para.save()
        pending = case_services.create_case(self.p2, "Cough")
        with self.assertRaises(ValidationError):
            services.prescribe(pending, [item(self.para)], self.doc)
        self.assertEqual(Prescription.objects.count(), 0)

    def test_allergy_match_on_ingredient_needs_acknowledgement(self):
        with self.assertRaises(services.AllergyWarning):
            services.prescribe(self.case, [item(self.amox)], self.doc)
        self.assertEqual(Prescription.objects.count(), 0)
        rx = services.prescribe(self.case, [item(self.amox)], self.doc, acknowledged=True)
        self.assertTrue(rx.allergy_warning_acknowledged)

    def test_no_warning_for_a_patient_without_that_allergy(self):
        case = case_services.create_case(self.p2, "Cough")
        case_services.route_case(case, self.surgery, self.head)
        case_services.assign_case(case, self.doc, self.head)
        rx = services.prescribe(case, [item(self.amox)], self.doc)
        self.assertFalse(rx.allergy_warning_acknowledged)


class DispensingTests(PharmacyBase):
    def test_full_dispense_uses_the_earliest_expiry_first(self):
        rx = self.prescription(quantity=40)
        services.dispense(rx, {rx.items.get().pk: 40}, self.pharm)
        rx.refresh_from_db()
        self.batch_early.refresh_from_db()
        self.batch_late.refresh_from_db()
        self.assertEqual(rx.status, "dispensed")
        self.assertIsNotNone(rx.completed_at)
        self.assertEqual(self.batch_early.quantity_remaining, 0)  # 30 taken first
        self.assertEqual(self.batch_late.quantity_remaining, 90)  # then 10
        self.assertEqual(Dispensing.objects.count(), 2)

    def test_partial_then_complete(self):
        rx = self.prescription(quantity=10)
        line = rx.items.get()
        services.dispense(rx, {line.pk: 4}, self.pharm)
        rx.refresh_from_db()
        self.assertEqual(rx.status, "partly_dispensed")
        with self.assertRaises(ValidationError):
            services.dispense(rx, {line.pk: 7}, self.pharm)  # only 6 left to dispense
        services.dispense(rx, {line.pk: 6}, self.pharm)
        rx.refresh_from_db()
        self.assertEqual(rx.status, "dispensed")

    def test_expired_stock_is_never_used(self):
        StockBatch.objects.all().update(expiry_date=days(-1))
        rx = self.prescription()
        with self.assertRaises(ValidationError):
            services.dispense(rx, {rx.items.get().pk: 5}, self.pharm)

    def test_shortage_changes_nothing_on_any_item(self):
        other = Drug.objects.create(name="Ibuprofen", strength="200 mg", unit="tablet")
        StockBatch.objects.create(drug=other, batch_number="I1", expiry_date=days(200),
                                  quantity_received=3, quantity_remaining=3)
        rx = services.prescribe(self.case, [item(self.para, 10), item(other, 10)], self.doc)
        quantities = {line.pk: 10 for line in rx.items.all()}
        with self.assertRaises(ValidationError):
            services.dispense(rx, quantities, self.pharm)  # ibuprofen is short
        self.batch_early.refresh_from_db()
        self.assertEqual(self.batch_early.quantity_remaining, 30)
        self.assertEqual(Dispensing.objects.count(), 0)
        self.assertEqual(PrescriptionItem.objects.filter(quantity_dispensed__gt=0).count(), 0)
        rx.refresh_from_db()
        self.assertEqual(rx.status, "prescribed")

    def test_must_name_a_quantity_and_a_drug_on_the_prescription(self):
        rx = self.prescription()
        with self.assertRaises(ValidationError):
            services.dispense(rx, {rx.items.get().pk: 0}, self.pharm)
        with self.assertRaises(ValidationError):
            services.dispense(rx, {999999: 1}, self.pharm)

    def test_allergy_on_dispensing_needs_acknowledgement(self):
        StockBatch.objects.create(drug=self.amox, batch_number="A1", expiry_date=days(200),
                                  quantity_received=20, quantity_remaining=20)
        rx = services.prescribe(self.case, [item(self.amox, 5)], self.doc, acknowledged=True)
        line = rx.items.get()
        with self.assertRaises(services.AllergyWarning):
            services.dispense(rx, {line.pk: 5}, self.pharm)
        services.dispense(rx, {line.pk: 5}, self.pharm, acknowledged=True)

    def test_cancelled_prescription_cannot_be_dispensed(self):
        rx = self.prescription()
        services.cancel_prescription(rx, self.doc, "wrong patient")
        rx.refresh_from_db()
        self.assertEqual(rx.status, "cancelled")
        with self.assertRaises(ValidationError):
            services.dispense(rx, {rx.items.get().pk: 1}, self.pharm)

    def test_cannot_cancel_after_something_was_dispensed(self):
        rx = self.prescription()
        services.dispense(rx, {rx.items.get().pk: 2}, self.pharm)
        with self.assertRaises(ValidationError):
            services.cancel_prescription(rx, self.doc, "")

    def test_close_needs_a_reason_and_a_partly_dispensed_prescription(self):
        rx = self.prescription()
        with self.assertRaises(ValidationError):
            services.close_prescription(rx, self.pharm, "out of stock")  # nothing dispensed yet
        services.dispense(rx, {rx.items.get().pk: 2}, self.pharm)
        with self.assertRaises(ValidationError):
            services.close_prescription(rx, self.pharm, "  ")
        services.close_prescription(rx, self.pharm, "supplier delay")
        rx.refresh_from_db()
        self.assertEqual(rx.status, "closed")
        with self.assertRaises(ValidationError):
            services.dispense(rx, {rx.items.get().pk: 1}, self.pharm)


class StockTests(PharmacyBase):
    def test_receive_stock_rules(self):
        batch = services.receive_stock(self.para, "N1", days(300), 50, self.pharm)
        self.assertEqual(batch.quantity_remaining, 50)
        with self.assertRaises(ValidationError):
            services.receive_stock(self.para, "N1", days(300), 50, self.pharm)  # same batch again
        with self.assertRaises(ValidationError):
            services.receive_stock(self.para, "N2", days(-1), 50, self.pharm)  # already expired
        with self.assertRaises(ValidationError):
            services.receive_stock(self.para, "N3", days(300), 0, self.pharm)
        with self.assertRaises(ValidationError):
            services.receive_stock(self.para, " ", days(300), 5, self.pharm)
        self.para.is_active = False
        self.para.save()
        with self.assertRaises(ValidationError):
            services.receive_stock(self.para, "N4", days(300), 5, self.pharm)

    def test_adjust_stock(self):
        services.adjust_stock(self.batch_early, -5, "damaged", "dropped", self.senior_pharm)
        self.batch_early.refresh_from_db()
        self.assertEqual(self.batch_early.quantity_remaining, 25)
        self.assertEqual(StockAdjustment.objects.count(), 1)
        with self.assertRaises(ValidationError):
            services.adjust_stock(self.batch_early, -26, "correction", "", self.senior_pharm)
        with self.assertRaises(ValidationError):
            services.adjust_stock(self.batch_early, 0, "correction", "", self.senior_pharm)

    def test_stock_levels_ignore_expired_stock(self):
        self.batch_early.expiry_date = days(-3)
        self.batch_early.save()
        drug = {d.pk: d for d in services.drug_stock()}[self.para.pk]
        self.assertEqual(drug.available, 100)
        self.assertEqual(drug.expired_stock, 30)
        self.assertEqual(list(services.expired_batches()), [self.batch_early])

    def test_out_low_and_ok_states(self):
        by_id = lambda: {d.pk: d for d in services.drug_stock()}
        self.assertEqual(by_id()[self.amox.pk].stock_state, "out")  # never stocked
        self.assertEqual(by_id()[self.para.pk].stock_state, "ok")
        self.para.reorder_level = 130
        self.para.save()
        self.assertEqual(by_id()[self.para.pk].stock_state, "low")
        self.assertEqual(services.low_stock_count(), 2)  # amoxicillin out, paracetamol low

    def test_expiring_soon(self):
        self.assertEqual(list(services.expiring_batches(days=120)), [self.batch_early])


class AuditTests(PharmacyBase):
    def test_actions_are_logged_without_drug_names_or_doses(self):
        rx = services.prescribe(self.case, [item(self.para, 5, dose="2 tablets")], self.doc)
        services.dispense(rx, {rx.items.get().pk: 5}, self.pharm)
        actions = set(AuditLog.objects.values_list("action", flat=True))
        self.assertTrue({"prescription_created", "prescription_dispensed"} <= actions)
        for entry in AuditLog.objects.filter(action__startswith="prescription_"):
            self.assertEqual(entry.patient, self.p1)
            for secret in ("Paracetamol", "paracetamol", "2 tablets"):
                self.assertNotIn(secret, entry.detail)
                self.assertNotIn(secret, entry.target_repr)

    def test_stock_changes_are_logged(self):
        services.receive_stock(self.para, "N1", days(300), 50, self.pharm)
        services.adjust_stock(self.batch_early, -1, "damaged", "", self.senior_pharm)
        actions = set(AuditLog.objects.values_list("action", flat=True))
        self.assertTrue({"stock_received", "stock_adjusted"} <= actions)


class PermissionTests(PharmacyBase):
    def test_who_can_prescribe(self):
        self.assertTrue(perms.can_prescribe(self.doc, self.case))
        self.assertTrue(perms.can_prescribe(self.head, self.case))  # head of the case's department
        self.assertFalse(perms.can_prescribe(self.other_doc, self.case))
        self.assertFalse(perms.can_prescribe(self.pharm, self.case))
        self.assertFalse(perms.can_prescribe(self.admin, self.case))
        pending = case_services.create_case(self.p2, "Cough")
        self.assertFalse(perms.can_prescribe(self.doc, pending))

    def test_who_can_dispense_cancel_close(self):
        rx = self.prescription()
        self.assertTrue(perms.can_dispense(self.pharm, rx))
        self.assertTrue(perms.can_dispense(self.pharm_head, rx))
        for user in (self.doc, self.head, self.admin, self.cleaner, self.p1.user):
            self.assertFalse(perms.can_dispense(user, rx), user.username)
        self.assertTrue(perms.can_cancel(self.doc, rx))
        self.assertTrue(perms.can_cancel(self.pharm, rx))
        self.assertFalse(perms.can_cancel(self.other_doc, rx))
        self.assertFalse(perms.can_close(self.pharm, rx))  # nothing dispensed yet

    def test_who_can_manage_stock(self):
        self.assertTrue(perms.can_manage_stock(self.senior_pharm))
        self.assertTrue(perms.can_manage_stock(self.pharm_head))
        self.assertTrue(perms.can_manage_stock(self.admin))
        self.assertFalse(perms.can_manage_stock(self.pharm))
        self.assertFalse(perms.can_manage_stock(self.doc))
        self.assertTrue(perms.can_receive_stock(self.pharm))
        self.assertFalse(perms.can_receive_stock(self.doc))

    def test_prescriptions_for_case_are_scoped(self):
        self.prescription()
        self.assertEqual(perms.prescriptions_for_case(self.p1.user, self.case).count(), 1)
        self.assertEqual(perms.prescriptions_for_case(self.p2.user, self.case).count(), 0)
        self.assertEqual(perms.prescriptions_for_case(self.doc, self.case).count(), 1)
        self.assertEqual(perms.prescriptions_for_case(self.other_doc, self.case).count(), 0)
        self.assertEqual(perms.prescriptions_for_case(self.cleaner, self.case).count(), 0)
        self.assertEqual(perms.prescriptions_for_case(self.admin, self.case).count(), 1)


class AreaViewTests(PharmacyBase):
    def test_worklist_and_stock_pages(self):
        urls = [reverse("pharmacy:worklist"), reverse("pharmacy:drugs"), reverse("pharmacy:stock")]
        for url in urls:
            self.client.logout()
            self.assertEqual(self.client.get(url).status_code, 302, url)  # anonymous
            for username in ("pharm", "seniorpharm", "pharmhead", "adminuser"):
                self.login(username)
                self.assertEqual(self.client.get(url).status_code, 200, f"{username} {url}")
            for username in ("doc", "head", "cleaner", "pat1"):
                self.login(username)
                self.assertEqual(self.client.get(url).status_code, 403, f"{username} {url}")

    def test_catalogue_edit_rights(self):
        create = reverse("pharmacy:drug_create")
        edit = reverse("pharmacy:drug_update", args=[self.para.pk])
        for url in (create, edit):
            for username in ("seniorpharm", "pharmhead", "adminuser"):
                self.login(username)
                self.assertEqual(self.client.get(url).status_code, 200, f"{username} {url}")
            for username in ("pharm", "doc", "pat1"):
                self.login(username)
                self.assertEqual(self.client.get(url).status_code, 403, f"{username} {url}")

    def test_new_drug_is_saved_and_audited(self):
        self.login("seniorpharm")
        self.client.post(reverse("pharmacy:drug_create"), {
            "name": "Metformin", "strength": "500 mg", "form": "tablet", "unit": "tablet",
            "ingredients": "metformin", "reorder_level": 20, "is_active": "on",
        })
        self.assertTrue(Drug.objects.filter(name="Metformin").exists())
        self.assertTrue(AuditLog.objects.filter(action="drug_created").exists())

    def test_receive_and_adjust_views(self):
        receive = reverse("pharmacy:receive")
        self.login("doc")
        self.assertEqual(self.client.get(receive).status_code, 403)
        self.login("pharm")
        self.assertEqual(self.client.get(receive).status_code, 200)
        response = self.client.post(receive, {"drug": self.para.pk, "batch_number": "V1",
                                              "expiry_date": days(200).isoformat(), "quantity": 40})
        self.assertRedirects(response, reverse("pharmacy:stock"))
        self.assertTrue(StockBatch.objects.filter(batch_number="V1", quantity_remaining=40).exists())
        adjust = reverse("pharmacy:adjust", args=[self.batch_early.pk])
        self.assertEqual(self.client.get(adjust).status_code, 403)  # junior cannot adjust
        self.login("seniorpharm")
        self.client.post(adjust, {"change": -10, "reason": "damaged", "note": ""})
        self.batch_early.refresh_from_db()
        self.assertEqual(self.batch_early.quantity_remaining, 20)

    def test_department_form_offers_the_pharmacy_flag(self):
        self.assertIn("is_pharmacy", DepartmentForm.Meta.fields)


def rx_post(rows, note="", acknowledge=False):
    data = {"form-TOTAL_FORMS": str(len(rows)), "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "0", "form-MAX_NUM_FORMS": "1000", "note": note}
    for i, row in enumerate(rows):
        for key, value in row.items():
            data[f"form-{i}-{key}"] = value
    if acknowledge:
        data["acknowledge_allergy"] = "on"
    return data


class PrescribeViewTests(PharmacyBase):
    def row(self, drug, quantity=10):
        return {"drug": drug.pk, "dose": "1 tablet", "frequency": "twice daily",
                "duration_days": 5, "quantity": quantity, "instructions": ""}

    def url(self):
        return reverse("pharmacy:prescribe", args=[self.case.pk])

    def test_who_may_open_the_prescribe_page(self):
        self.login("doc")
        self.assertEqual(self.client.get(self.url()).status_code, 200)
        self.login("head")
        self.assertEqual(self.client.get(self.url()).status_code, 200)
        for username in ("pat1", "adminuser"):  # can see the case, but may not prescribe
            self.login(username)
            self.assertEqual(self.client.get(self.url()).status_code, 403, username)
        for username in ("otherdoc", "pharm", "pat2", "cleaner"):  # cannot even see the case
            self.login(username)
            self.assertEqual(self.client.get(self.url()).status_code, 404, username)

    def test_doctor_prescribes_from_the_page(self):
        self.login("doc")
        rows = [self.row(self.para), {}, {}]
        response = self.client.post(self.url(), rx_post(rows, note="after food"))
        self.assertRedirects(response, reverse("cases:detail", args=[self.case.pk]), fetch_redirect_response=False)
        rx = Prescription.objects.get()
        self.assertEqual(rx.note, "after food")
        self.assertEqual(rx.items.count(), 1)

    def test_blank_form_is_rejected(self):
        self.login("doc")
        response = self.client.post(self.url(), rx_post([{}, {}, {}]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Prescription.objects.count(), 0)

    def test_allergy_warning_then_acknowledged(self):
        self.login("doc")
        rows = [self.row(self.amox)]
        first = self.client.post(self.url(), rx_post(rows))
        self.assertEqual(first.status_code, 200)
        self.assertContains(first, "Penicillin allergy is recorded")
        self.assertEqual(Prescription.objects.count(), 0)
        second = self.client.post(self.url(), rx_post(rows, acknowledge=True))
        self.assertEqual(second.status_code, 302)
        self.assertTrue(Prescription.objects.get().allergy_warning_acknowledged)


class PrescriptionViewTests(PharmacyBase):
    def setUp(self):
        super().setUp()
        self.rx = self.prescription()
        self.url = reverse("pharmacy:prescription", args=[self.rx.pk])

    def test_who_can_see_a_prescription(self):
        for username in ("pat1", "doc", "head", "pharm", "pharmhead", "adminuser"):
            self.login(username)
            self.assertEqual(self.client.get(self.url).status_code, 200, username)
        for username in ("pat2", "otherdoc", "cleaner"):
            self.login(username)
            self.assertEqual(self.client.get(self.url).status_code, 404, username)

    def test_staff_views_are_audited_but_patient_views_are_not(self):
        self.login("pat1")
        self.client.get(self.url)
        self.assertFalse(AuditLog.objects.filter(action="prescription_viewed").exists())
        self.login("pharm")
        self.client.get(self.url)
        self.assertEqual(AuditLog.objects.filter(action="prescription_viewed").count(), 1)

    def test_patient_does_not_see_the_pharmacy_note(self):
        Prescription.objects.filter(pk=self.rx.pk).update(note="internal pharmacy note")
        self.login("pat1")
        self.assertNotContains(self.client.get(self.url), "internal pharmacy note")
        self.login("pharm")
        self.assertContains(self.client.get(self.url), "internal pharmacy note")

    def test_dispense_form_only_for_pharmacy_staff(self):
        self.login("pharm")
        self.assertContains(self.client.get(self.url), "Dispense now")
        for username in ("doc", "adminuser", "pat1"):
            self.login(username)
            self.assertNotContains(self.client.get(self.url), "Dispense now")

    def test_dispense_through_the_view(self):
        line = self.rx.items.get()
        dispense = reverse("pharmacy:dispense", args=[self.rx.pk])
        for username in ("doc", "adminuser", "pat1"):
            self.login(username)
            self.assertEqual(self.client.post(dispense, {f"item_{line.pk}": 5}).status_code, 403, username)
        self.login("pharm")
        self.client.post(dispense, {f"item_{line.pk}": 10})
        self.rx.refresh_from_db()
        self.assertEqual(self.rx.status, "dispensed")

    def test_dispense_too_much_shows_an_error_and_changes_nothing(self):
        line = self.rx.items.get()
        self.login("pharm")
        self.client.post(reverse("pharmacy:dispense", args=[self.rx.pk]), {f"item_{line.pk}": 99})
        self.rx.refresh_from_db()
        self.assertEqual(self.rx.status, "prescribed")

    def test_dispense_rejects_get(self):
        self.login("pharm")
        self.assertEqual(self.client.get(reverse("pharmacy:dispense", args=[self.rx.pk])).status_code, 405)

    def test_cancel_view(self):
        cancel = reverse("pharmacy:cancel", args=[self.rx.pk])
        self.login("otherdoc")
        self.assertEqual(self.client.post(cancel, {"reason": "x"}).status_code, 404)
        self.login("pat1")
        self.assertEqual(self.client.post(cancel, {"reason": "x"}).status_code, 403)
        self.login("doc")
        self.client.post(cancel, {"reason": "wrong dose"})
        self.rx.refresh_from_db()
        self.assertEqual(self.rx.status, "cancelled")

    def test_close_view(self):
        line = self.rx.items.get()
        services.dispense(self.rx, {line.pk: 3}, self.pharm)
        close = reverse("pharmacy:close", args=[self.rx.pk])
        self.login("doc")
        self.assertEqual(self.client.post(close, {"reason": "x"}).status_code, 403)
        self.login("pharm")
        self.client.post(close, {"reason": ""})  # reason missing
        self.rx.refresh_from_db()
        self.assertEqual(self.rx.status, "partly_dispensed")
        self.client.post(close, {"reason": "supplier delay"})
        self.rx.refresh_from_db()
        self.assertEqual(self.rx.status, "closed")


class PatientViewTests(PharmacyBase):
    def test_my_prescriptions_shows_only_my_own(self):
        self.prescription()
        other_case = case_services.create_case(self.p2, "Cough")
        case_services.route_case(other_case, self.surgery, self.head)
        case_services.assign_case(other_case, self.other_doc, self.head)
        services.prescribe(other_case, [item(self.para, 7)], self.other_doc)
        self.login("pat1")
        response = self.client.get(reverse("pharmacy:mine"))
        self.assertEqual(len(response.context["prescriptions"]), 1)
        self.login("pat2")
        self.assertEqual(len(self.client.get(reverse("pharmacy:mine")).context["prescriptions"]), 1)

    def test_staff_cannot_open_the_patient_page(self):
        for username in ("doc", "pharm", "adminuser"):
            self.login(username)
            self.assertEqual(self.client.get(reverse("pharmacy:mine")).status_code, 403, username)


class DashboardTests(PharmacyBase):
    def test_pharmacy_staff_get_the_pharmacy_dashboard(self):
        from accounts.dashboards import _role_dashboard
        self.prescription()
        dash = _role_dashboard(self.pharm)
        self.assertEqual(dash["kind"], "pharmacy")
        self.assertEqual(dash["counts"]["waiting"], 1)
        self.assertEqual(len(dash["waiting"]), 1)
        self.assertEqual(_role_dashboard(self.doc)["kind"], "medical")

    def test_patient_dashboard_counts_prescriptions(self):
        from accounts.dashboards import _role_dashboard
        self.prescription()
        self.assertEqual(_role_dashboard(self.p1.user)["prescriptions_count"], 1)
        self.assertEqual(_role_dashboard(self.p2.user)["prescriptions_count"], 0)


class CasePageTests(PharmacyBase):
    """The Prescriptions block on the case page (cases/case_detail.html)."""

    def page(self):
        return self.client.get(reverse("cases:detail", args=[self.case.pk]))

    def test_assigned_doctor_gets_the_prescribe_link(self):
        self.login("doc")
        self.assertContains(self.page(), reverse("pharmacy:prescribe", args=[self.case.pk]))

    def test_prescription_is_listed_with_a_link_to_it(self):
        rx = self.prescription()
        self.login("doc")
        response = self.page()
        self.assertContains(response, "Paracetamol")
        self.assertContains(response, reverse("pharmacy:prescription", args=[rx.pk]))

    def test_patient_sees_their_prescription_but_no_prescribe_link(self):
        self.prescription()
        self.login("pat1")
        response = self.page()
        self.assertContains(response, "Paracetamol")
        self.assertNotContains(response, reverse("pharmacy:prescribe", args=[self.case.pk]))

    def test_admin_sees_prescriptions_but_cannot_prescribe_from_the_page(self):
        self.prescription()
        self.login("adminuser")
        response = self.page()
        self.assertContains(response, "Paracetamol")
        self.assertNotContains(response, reverse("pharmacy:prescribe", args=[self.case.pk]))

    def test_no_block_when_there_is_nothing_to_show_or_do(self):
        # A completed case: nothing can be prescribed, and there are no prescriptions
        case_services.change_status(self.case, "completed", self.doc)
        self.login("doc")
        self.assertNotContains(self.page(), "Prescriptions")
