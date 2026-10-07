from django.urls import path

from . import views

app_name = "cases"

urlpatterns = [
    path("", views.CaseHomeView.as_view(), name="home"),
    path("new/", views.CaseCreateView.as_view(), name="new"),
    path("mine/", views.MyCasesView.as_view(), name="mine"),
    path("triage/", views.TriageQueueView.as_view(), name="triage"),
    path("department/", views.DepartmentQueueView.as_view(), name="department"),
    path("assigned/", views.AssignedCasesView.as_view(), name="assigned"),
    path("all/", views.AllCasesView.as_view(), name="all"),
    path("<int:pk>/", views.CaseDetailView.as_view(), name="detail"),
    path("<int:pk>/route/", views.CaseRouteView.as_view(), name="route"),
    path("<int:pk>/assign/", views.CaseAssignView.as_view(), name="assign"),
    path("<int:pk>/status/", views.CaseStatusView.as_view(), name="status"),
]
