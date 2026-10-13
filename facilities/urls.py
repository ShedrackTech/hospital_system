from django.urls import path

from . import views, ward_views

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
    # Admissions
    path("admissions/", views.AdmissionListView.as_view(), name="admission_list"),
    path("cases/<int:case_pk>/admit/", views.AdmitView.as_view(), name="admit"),
    path(
        "admissions/<int:pk>/discharge/",
        views.DischargeView.as_view(),
        name="discharge",
    ),
    # Nurses and wards
    path("ward-staff/", ward_views.WardStaffView.as_view(), name="ward_staff"),
    path("ward-staff/assign/", ward_views.WardAssignView.as_view(), name="ward_assign"),
    path("ward-staff/<int:pk>/remove/", ward_views.WardAssignmentRemoveView.as_view(),
         name="ward_unassign"),
    path("my-ward/", ward_views.MyWardView.as_view(), name="my_ward"),
]
