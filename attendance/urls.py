from django.urls import path

from . import roster_views, views

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
    # Duty roster
    path("roster/", roster_views.RosterManageView.as_view(), name="roster"),
    path("roster/mine/", roster_views.MyRosterView.as_view(), name="roster_mine"),
    path("roster/assign/", roster_views.RosterAssignView.as_view(), name="roster_assign"),
    path("roster/entry/<int:pk>/remove/", roster_views.RosterRemoveView.as_view(),
         name="roster_remove"),
    path("roster/shifts/", roster_views.ShiftTypeListView.as_view(), name="shifts"),
    path("roster/shifts/new/", roster_views.ShiftTypeCreateView.as_view(), name="shift_create"),
    path("roster/shifts/<int:pk>/edit/", roster_views.ShiftTypeUpdateView.as_view(),
         name="shift_update"),
]
