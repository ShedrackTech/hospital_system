from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Bed, Building, Ward

User = get_user_model()


class FacilitiesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.sub_admin = User.objects.create_user(
            "subadmin", password="pass12345", role=User.Role.SUB_ADMIN
        )
        cls.nurse = User.objects.create_user(
            "nurse1", password="pass12345", role=User.Role.NURSE
        )
        cls.patient = User.objects.create_user(
            "patient1", password="pass12345", role=User.Role.PATIENT
        )
        cls.building = Building.objects.create(name="Block A")
        cls.ward = Ward.objects.create(
            name="Male General", building=cls.building, ward_type=Ward.WardType.GENERAL
        )
        Bed.objects.create(ward=cls.ward, number="B1", is_occupied=True)
        Bed.objects.create(ward=cls.ward, number="B2")
        Bed.objects.create(ward=cls.ward, number="B3")

    def test_anonymous_is_sent_to_login(self):
        response = self.client.get(reverse("facilities:overview"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_non_admins_get_403(self):
        for user in (self.nurse, self.patient):
            self.client.force_login(user)
            response = self.client.get(reverse("facilities:overview"))
            self.assertEqual(response.status_code, 403)

    def test_overview_shows_occupancy(self):
        self.client.force_login(self.sub_admin)
        response = self.client.get(reverse("facilities:overview"))
        self.assertEqual(response.status_code, 200)
        ward = response.context["buildings"][0].wards.all()[0]
        self.assertEqual(ward.total_beds, 3)
        self.assertEqual(ward.occupied_beds, 1)
        self.assertEqual(ward.free_beds, 2)

    def test_create_building_and_ward(self):
        self.client.force_login(self.sub_admin)
        self.client.post(reverse("facilities:building_create"), {"name": "Block B"})
        building = Building.objects.get(name="Block B")
        response = self.client.post(
            reverse("facilities:ward_create"),
            {
                "name": "ICU",
                "building": building.pk,
                "ward_type": "icu",
                "floor": "1",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Ward.objects.filter(name="ICU", building=building).exists())

    def test_duplicate_ward_name_in_same_building_is_rejected(self):
        self.client.force_login(self.sub_admin)
        response = self.client.post(
            reverse("facilities:ward_create"),
            {"name": "Male General", "building": self.building.pk,
             "ward_type": "general", "floor": ""},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Ward.objects.filter(name="Male General").count(), 1)

    def test_bulk_add_beds_skips_existing_numbers(self):
        self.client.force_login(self.sub_admin)
        response = self.client.post(
            reverse("facilities:bed_add", args=[self.ward.pk]),
            {"prefix": "B", "start": 2, "count": 4},  # B2..B5, B2 and B3 exist
        )
        self.assertEqual(response.status_code, 302)
        numbers = set(self.ward.beds.values_list("number", flat=True))
        self.assertEqual(numbers, {"B1", "B2", "B3", "B4", "B5"})

    def test_non_admin_cannot_add_beds(self):
        self.client.force_login(self.nurse)
        response = self.client.post(
            reverse("facilities:bed_add", args=[self.ward.pk]),
            {"prefix": "X", "start": 1, "count": 2},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.ward.beds.count(), 3)

    def test_ward_detail_page(self):
        self.client.force_login(self.sub_admin)
        response = self.client.get(reverse("facilities:ward_detail", args=[self.ward.pk]))
        self.assertContains(response, "Male General")
        self.assertEqual(response.context["free_beds"], 2)
