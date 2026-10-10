from django.urls import path

from . import views

app_name = "datarequests"

urlpatterns = [
    path("", views.MyRequestsView.as_view(), name="mine"),
    path("new/", views.NewRequestView.as_view(), name="new"),
    path("manage/", views.ManageListView.as_view(), name="manage"),
    path("<int:pk>/", views.RequestDetailView.as_view(), name="detail"),
    path("<int:pk>/handle/", views.RequestHandleView.as_view(), name="handle"),
]
