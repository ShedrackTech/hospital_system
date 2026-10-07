from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("departments/", include("departments.urls")),
    path("facilities/", include("facilities.urls")),
    path("patients/", include("patients.urls")),
    # Temporary: send the home page to login until the public website app is built
    path("", RedirectView.as_view(pattern_name="accounts:login", permanent=False)),
    path("cases/", include("cases.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
