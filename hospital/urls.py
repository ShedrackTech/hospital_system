from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    # Public website (home page, about, departments, doctors, services, contact, blog)
    # and the admin pages under /site/ that run it.
    path("", include("website.urls")),
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("departments/", include("departments.urls")),
    path("facilities/", include("facilities.urls")),
    path("patients/", include("patients.urls")),
    path("audit/", include("core.urls")),
    path("laboratory/", include("laboratory.urls")),
    path("pharmacy/", include("pharmacy.urls")),
    path("attendance/", include("attendance.urls")),
    path("requests/", include("datarequests.urls")),
    path("cases/", include("cases.urls")),
    path("billing/", include("billing.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
