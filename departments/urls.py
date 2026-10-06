from django.urls import path

from . import views

app_name = "departments"

urlpatterns = [
    path("", views.DepartmentListView.as_view(), name="list"),
    path("new/", views.DepartmentCreateView.as_view(), name="create"),
    path("<int:pk>/", views.DepartmentDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", views.DepartmentUpdateView.as_view(), name="update"),
    path("staff/new/", views.StaffProfileCreateView.as_view(), name="staff_create"),
    path(
        "staff/<int:pk>/edit/",
        views.StaffProfileUpdateView.as_view(),
        name="staff_update",
    ),
]
