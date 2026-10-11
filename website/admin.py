from django.contrib import admin

from .models import BlogPost, ContactMessage, DoctorListing, Service, SiteInfo


@admin.register(SiteInfo)
class SiteInfoAdmin(admin.ModelAdmin):
    list_display = ("__str__", "phone", "email", "updated_at")
    search_fields = ("address", "phone", "email")


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ("name", "display_order", "is_active")
    search_fields = ("name", "description")
    list_filter = ("is_active",)


@admin.register(DoctorListing)
class DoctorListingAdmin(admin.ModelAdmin):
    list_display = ("user", "display_order", "is_listed", "updated_at")
    search_fields = ("user__username", "user__first_name", "user__last_name", "bio")
    list_filter = ("is_listed",)


@admin.register(BlogPost)
class BlogPostAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "status", "author", "published_at", "created_at")
    search_fields = ("title", "summary", "body")
    list_filter = ("category", "status")
    readonly_fields = ("slug", "published_at")


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ("subject", "reason", "name", "email", "is_handled", "created_at")
    search_fields = ("subject", "name", "email", "message")
    list_filter = ("reason", "is_handled")
