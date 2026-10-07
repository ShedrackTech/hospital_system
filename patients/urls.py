from django.urls import path

from . import views

app_name = "patients"

urlpatterns = [
    path("", views.PatientListView.as_view(), name="list"),
    path("register/", views.PatientRegisterView.as_view(), name="register"),
    path("registered/", views.RegistrationCompleteView.as_view(), name="registered"),
    path("new/", views.StaffRegisterPatientView.as_view(), name="staff_register"),
    path("me/", views.MyProfileView.as_view(), name="my_profile"),
    path("cards/", views.CardDeskView.as_view(), name="card_desk"),
    path("cards/prices/", views.CardPricesView.as_view(), name="card_prices"),
    path("families/", views.FamilyListView.as_view(), name="family_list"),
    path("families/<int:pk>/", views.FamilyDetailView.as_view(), name="family_detail"),
    path("<int:pk>/", views.PatientDetailView.as_view(), name="detail"),
]
