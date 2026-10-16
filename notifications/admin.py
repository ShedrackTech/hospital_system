from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    """Read-only: notifications are created by the portal, not typed in by hand."""

    list_display = ("id", "recipient", "kind", "title", "created_at", "read_at")
    list_filter = ("kind",)
    search_fields = ("recipient__login_id", "title")

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
