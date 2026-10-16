from django.urls import path

from . import views

app_name = "laboratory"

urlpatterns = [
    path("", views.WorklistView.as_view(), name="worklist"),
    path("tests/", views.TestListView.as_view(), name="tests"),
    path("tests/new/", views.TestCreateView.as_view(), name="test_create"),
    path("tests/<int:pk>/edit/", views.TestUpdateView.as_view(), name="test_update"),
    path("order/<int:case_pk>/", views.OrderView.as_view(), name="order"),
    path("results/<int:pk>/", views.ResultDetailView.as_view(), name="result"),
    path("results/<int:pk>/enter/", views.ResultEnterView.as_view(), name="result_enter"),
    path("results/<int:pk>/release/", views.ResultReleaseView.as_view(), name="result_release"),
    path("results/<int:pk>/amend/", views.ResultAmendView.as_view(), name="result_amend"),
    path("results/<int:pk>/cancel/", views.ResultCancelView.as_view(), name="result_cancel"),
    path("results/<int:pk>/print/", views.ResultPrintView.as_view(), name="print"),
    path("mine/", views.MyResultsView.as_view(), name="mine"),
]
