from django.contrib.auth.views import LogoutView
from django.urls import path

from . import staff_views, views

app_name = "accounts"

urlpatterns = [
    path("login/", views.PortalLoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("dashboard/", views.dashboard, name="dashboard"),
    # Staff management (admin roles only)
    path("staff/", staff_views.StaffListView.as_view(), name="staff_list"),
    path("staff/new/", staff_views.StaffCreateView.as_view(), name="staff_create"),
    path("staff/<int:pk>/", staff_views.StaffDetailView.as_view(), name="staff_detail"),
    path("staff/<int:pk>/edit/", staff_views.StaffUpdateView.as_view(), name="staff_update"),
    path("staff/<int:pk>/password/", staff_views.StaffPasswordView.as_view(), name="staff_password"),
    path("staff/<int:pk>/deactivate/",
         staff_views.StaffActiveView.as_view(activate=False), name="staff_deactivate"),
    path("staff/<int:pk>/reactivate/",
         staff_views.StaffActiveView.as_view(activate=True), name="staff_reactivate"),
]
