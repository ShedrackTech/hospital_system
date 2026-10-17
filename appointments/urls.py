from django.urls import path

from . import views

app_name = "appointments"

urlpatterns = [
    path("", views.home, name="home"),
    path("mine/", views.mine, name="mine"),
    path("book/", views.book, name="book"),
    path("all/", views.staff_list, name="staff_list"),
    path("availability/", views.availability, name="availability"),
    path("availability/<int:pk>/remove/", views.availability_remove, name="availability_remove"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/cancel/", views.cancel, name="cancel"),
    path("<int:pk>/close/", views.close, name="close"),
    path("<int:pk>/link-case/", views.link_case, name="link_case"),
    path("<int:pk>/unlink-case/", views.unlink_case, name="unlink_case"),
]
