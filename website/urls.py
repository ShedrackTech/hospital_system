from django.urls import path

from . import manage_views as manage
from . import views

app_name = "website"

urlpatterns = [
    # Public site: one home page with sections. The old page addresses redirect to their section.
    path("", views.HomeView.as_view(), name="home"),
    path("about/", views.SectionRedirectView.as_view(anchor="about"), name="about"),
    # Not "departments/": the portal already owns that address (departments.urls) and it needs a login.
    path("our-departments/", views.SectionRedirectView.as_view(anchor="departments"), name="departments"),
    path("doctors/", views.SectionRedirectView.as_view(anchor="doctors"), name="doctors"),
    path("services/", views.SectionRedirectView.as_view(anchor="services"), name="services"),
    path("contact/", views.ContactView.as_view(), name="contact"),  # the form on the home page posts here
    path("blog/", views.BlogListView.as_view(), name="blog"),
    path("blog/<slug:slug>/", views.BlogDetailView.as_view(), name="blog_detail"),

    # Portal pages for administrators
    path("site/", manage.ManageHomeView.as_view(), name="manage_home"),
    path("site/info/", manage.SiteInfoUpdateView.as_view(), name="manage_info"),
    path("site/posts/", manage.PostListView.as_view(), name="manage_posts"),
    path("site/posts/new/", manage.PostCreateView.as_view(), name="manage_post_new"),
    path("site/posts/<int:pk>/edit/", manage.PostUpdateView.as_view(), name="manage_post_edit"),
    path("site/services/", manage.ServiceListView.as_view(), name="manage_services"),
    path("site/services/new/", manage.ServiceCreateView.as_view(), name="manage_service_new"),
    path("site/services/<int:pk>/edit/", manage.ServiceUpdateView.as_view(), name="manage_service_edit"),
    path("site/doctors/", manage.DoctorListingListView.as_view(), name="manage_doctors"),
    path("site/doctors/new/", manage.DoctorListingCreateView.as_view(), name="manage_doctor_new"),
    path("site/doctors/<int:pk>/edit/", manage.DoctorListingUpdateView.as_view(), name="manage_doctor_edit"),
    path("site/messages/", manage.MessageListView.as_view(), name="manage_messages"),
    path("site/messages/<int:pk>/", manage.MessageDetailView.as_view(), name="manage_message"),
    path("site/messages/<int:pk>/toggle/", manage.MessageToggleView.as_view(), name="manage_message_toggle"),
]
