from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("", views.notification_list, name="list"),
    path("read-all/", views.mark_all, name="mark_all"),
    path("<int:pk>/open/", views.open_notification, name="open"),
]
