from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Read-only. Nobody can add, edit or delete entries here."""

    list_display = ("created_at", "actor_label", "action", "target_repr",
                    "patient", "ip_address")
    list_filter = ("action", "created_at")
    search_fields = ("actor_label", "target_repr", "detail",
                     "patient__user__login_id", "patient__user__first_name",
                     "patient__user__last_name")
    list_select_related = ("patient", "patient__user")
    date_hierarchy = "created_at"

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
