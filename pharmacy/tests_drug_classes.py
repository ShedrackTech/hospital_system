"""The allergy check also matches drug classes (for example Penicillins)."""
import datetime

from django.core.exceptions import ValidationError
from django.urls import reverse

from patients.models import Allergy

from . import services
from . import tests as base
from .models import Drug, Prescription


def make_allergy(patient, name):
    """Create an allergy, filling any other required field so the test does not depend on the exact fields."""
    values = {}
    for f in Allergy._meta.concrete_fields:
        if f.primary_key or f.name in ("patient", "name") or f.has_default() or f.null or f.blank:
            continue
        if f.choices:
            values[f.name] = f.choices[0][0]
        elif f.get_internal_type() == "DateField":
            values[f.name] = datetime.date(2020, 1, 1)
        elif f.get_internal_type() in ("IntegerField", "PositiveIntegerField", "SmallIntegerField"):
            values[f.name] = 1
        else:
            values[f.name] = "x"
    return Allergy.objects.create(patient=patient, name=name, **values)


def make_drug(name, drug_class="", ingredients="", strength="500 mg"):
    return Drug.objects.create(name=name, strength=strength, form="tablet",
                               drug_class=drug_class, ingredients=ingredients)


@base.FAST
class DrugClassAllergyTests(base.PharmacyBase):
    def setUp(self):
        super().setUp()
        self.patient = self.case.patient
        # The shared test base may already record allergies for this patient. Start from none,
        # so each test controls exactly which allergies exist.
        self.patient.allergies.all().delete()
        self.amox = make_drug("Amoxicillin", "Penicillins")
        self.ampi = make_drug("Ampicillin", "Penicillins")

    def test_an_allergy_named_after_the_class_flags_every_drug_in_it(self):
        make_allergy(self.patient, "Penicillin")
        found = services.allergy_conflicts(self.patient, [self.amox, self.ampi, self.para])
        self.assertEqual({c[0] for c in found}, {self.amox, self.ampi})
        self.assertTrue(all(c.via_class == "Penicillins" for c in found))

    def test_an_allergy_to_one_drug_flags_another_drug_of_its_class(self):
        make_allergy(self.patient, "Amoxicillin")
        found = services.allergy_conflicts(self.patient, [self.amox, self.ampi])
        by_drug = {c[0]: c.via_class for c in found}
        self.assertEqual(by_drug, {self.amox: "", self.ampi: "Penicillins"})  # name match, then class match

    def test_a_drug_of_another_class_is_not_flagged(self):
        make_allergy(self.patient, "Penicillin")
        analgesic = make_drug("Ibuprofen", "NSAIDs")
        self.assertEqual(services.allergy_conflicts(self.patient, [analgesic, self.para]), [])

    def test_without_a_class_only_the_old_name_and_ingredient_match_applies(self):
        no_class = make_drug("Flucloxacillin")
        make_allergy(self.patient, "Amoxicillin")
        self.assertEqual(services.allergy_conflicts(self.patient, [no_class]), [])
        make_allergy(self.patient, "Flucloxacillin")
        self.assertEqual(len(services.allergy_conflicts(self.patient, [no_class])), 1)

    def test_very_short_class_names_are_ignored(self):
        make_allergy(self.patient, "Penicillin")
        odd = make_drug("Oddmed", "pen")
        self.assertEqual(services.allergy_conflicts(self.patient, [odd]), [])

    def test_conflicts_still_unpack_as_drug_and_allergy(self):
        make_allergy(self.patient, "Penicillin")
        for drug, allergy in services.allergy_conflicts(self.patient, [self.ampi]):
            self.assertEqual((drug, allergy.name), (self.ampi, "Penicillin"))

    def test_prescribing_needs_acknowledgement_and_the_warning_names_the_class(self):
        make_allergy(self.patient, "Penicillin")
        with self.assertRaises(services.AllergyWarning) as ctx:
            services.prescribe(self.case, [base.item(self.ampi)], self.doc)
        self.assertIn("same drug class: Penicillins", " ".join(ctx.exception.messages))
        self.assertEqual(Prescription.objects.count(), 0)
        rx = services.prescribe(self.case, [base.item(self.ampi)], self.doc, acknowledged=True)
        self.assertTrue(rx.allergy_warning_acknowledged)

    def test_a_drug_of_another_class_prescribes_without_a_warning(self):
        make_allergy(self.patient, "Penicillin")
        rx = services.prescribe(self.case, [base.item(self.para)], self.doc)
        self.assertFalse(rx.allergy_warning_acknowledged)

    def test_dispensing_checks_the_class_too(self):
        rx = services.prescribe(self.case, [base.item(self.ampi)], self.doc)
        make_allergy(self.patient, "Penicillin")  # recorded after the prescription was written
        line = rx.items.get()
        with self.assertRaises(services.AllergyWarning):
            services.dispense(rx, {line.pk: 1}, self.pharm)

    def test_the_prescription_page_says_the_class_matched(self):
        rx = services.prescribe(self.case, [base.item(self.ampi)], self.doc)
        make_allergy(self.patient, "Penicillin")
        self.login("pharm")
        page = self.client.get(reverse("pharmacy:prescription", args=[rx.pk]))
        self.assertContains(page, "same drug class: Penicillins")
