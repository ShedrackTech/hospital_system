from django.urls import path

from . import views

app_name = "pharmacy"

urlpatterns = [
    path("", views.WorklistView.as_view(), name="worklist"),
    path("drugs/", views.DrugListView.as_view(), name="drugs"),
    path("drugs/new/", views.DrugCreateView.as_view(), name="drug_create"),
    path("drugs/<int:pk>/edit/", views.DrugUpdateView.as_view(), name="drug_update"),
    path("stock/", views.StockView.as_view(), name="stock"),
    path("stock/receive/", views.ReceiveStockView.as_view(), name="receive"),
    path("stock/batches/<int:pk>/adjust/", views.AdjustStockView.as_view(), name="adjust"),
    path("prescribe/<int:case_pk>/", views.PrescribeView.as_view(), name="prescribe"),
    path("prescriptions/<int:pk>/", views.PrescriptionDetailView.as_view(), name="prescription"),
    path("prescriptions/<int:pk>/dispense/", views.DispenseView.as_view(), name="dispense"),
    path("prescriptions/<int:pk>/cancel/", views.CancelView.as_view(), name="cancel"),
    path("prescriptions/<int:pk>/close/", views.CloseView.as_view(), name="close"),
    path("mine/", views.MyPrescriptionsView.as_view(), name="mine"),
]
