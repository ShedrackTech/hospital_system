from django.urls import path

from . import views

app_name = "billing"

urlpatterns = [
    path("", views.home, name="home"),
    path("mine/", views.mine, name="mine"),
    path("all/", views.invoice_list, name="invoice_list"),
    path("new/", views.invoice_new, name="new"),
    path("prices/", views.items, name="items"),
    path("prices/new/", views.item_form, name="item_new"),
    path("prices/<int:pk>/edit/", views.item_form, name="item_edit"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/pay/", views.pay, name="pay"),
    path("<int:pk>/void/", views.void, name="void"),
    path("<int:pk>/print/", views.invoice_print, name="print"),
]
