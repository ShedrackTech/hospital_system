from django.urls import path

from . import views

app_name = "facilities"

urlpatterns = [
    path("", views.FacilityOverviewView.as_view(), name="overview"),
    path("buildings/new/", views.BuildingCreateView.as_view(), name="building_create"),
    path(
        "buildings/<int:pk>/edit/",
        views.BuildingUpdateView.as_view(),
        name="building_update",
    ),
    path("wards/new/", views.WardCreateView.as_view(), name="ward_create"),
    path("wards/<int:pk>/", views.WardDetailView.as_view(), name="ward_detail"),
    path("wards/<int:pk>/edit/", views.WardUpdateView.as_view(), name="ward_update"),
    path("wards/<int:pk>/beds/add/", views.BedAddView.as_view(), name="bed_add"),
]
