from django.urls import path

from . import views

app_name = "attendance"

urlpatterns = [
    path("", views.MyAttendanceView.as_view(), name="mine"),
    path("clock-in/", views.ClockInView.as_view(), name="clock_in"),
    path("clock-out/", views.ClockOutView.as_view(), name="clock_out"),
    path("team/", views.TeamAttendanceView.as_view(), name="team"),
    path("record/new/", views.OfficerRecordView.as_view(), name="officer_record"),
    path("record/<int:pk>/confirm/", views.ConfirmView.as_view(), name="confirm"),
    path("record/<int:pk>/departure/", views.DepartureView.as_view(), name="departure"),
    path("record/<int:pk>/correct/", views.CorrectView.as_view(), name="correct"),
]
