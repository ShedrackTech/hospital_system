from django.contrib import admin

from .models import DataRequest


@admin.register(DataRequest)
class DataRequestAdmin(admin.ModelAdmin):
    """Read-only: requests are handled in the portal so every step is audited."""

    list_display = ("id", "kind", "subject", "patient", "status", "created_at", "handled_by")
    list_filter = ("status", "kind", "created_at")
    search_fields = ("subject", "patient__user__login_id",
                     "patient__user__first_name", "patient__user__last_name")
    list_select_related = ("patient", "patient__user", "handled_by")

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
