warning: in the working copy of 'hospital/urls.py', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'templates/base.html', LF will be replaced by CRLF the next time Git touches it
[1mdiff --git a/hospital/urls.py b/hospital/urls.py[m
[1mindex 132f80e..03b55b2 100644[m
[1m--- a/hospital/urls.py[m
[1m+++ b/hospital/urls.py[m
[36m@@ -2,7 +2,6 @@[m [mfrom django.conf import settings[m
 from django.conf.urls.static import static[m
 from django.contrib import admin[m
 from django.urls import include, path[m
[31m-from django.views.generic import RedirectView[m
 [m
 urlpatterns = [[m
     path("admin/", admin.site.urls),[m
[36m@@ -14,9 +13,10 @@[m [murlpatterns = [[m
     path("laboratory/", include("laboratory.urls")),[m
     path("attendance/", include("attendance.urls")),[m
     path("requests/", include("datarequests.urls")),[m
[31m-    # Temporary: send the home page to login until the public website app is built[m
[31m-    path("", RedirectView.as_view(pattern_name="accounts:login", permanent=False)),[m
     path("cases/", include("cases.urls")),[m
[32m+[m[32m    # Public website (home page, about, departments, doctors, services, contact, blog)[m
[32m+[m[32m    # and the admin pages under /site/ that run it.[m
[32m+[m[32m    path("", include("website.urls")),[m
 ][m
 [m
 if settings.DEBUG:[m
[1mdiff --git a/templates/base.html b/templates/base.html[m
[1mindex de60f82..666e012 100644[m
[1m--- a/templates/base.html[m
[1m+++ b/templates/base.html[m
[36m@@ -67,6 +67,7 @@[m
       <a href="{% url 'facilities:admission_list' %}">Admissions</a>[m
       <a href="{% url 'accounts:staff_list' %}">Staff</a>[m
       <a href="{% url 'datarequests:manage' %}">Data requests</a>[m
[32m+[m[32m      <a href="{% url 'website:manage_home' %}">Website</a>[m
       <a href="{% url 'core:audit_list' %}">Audit log</a>[m
     {% endif %}[m
     <form method="post" action="{% url 'accounts:logout' %}">[m
