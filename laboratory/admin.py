from django.contrib import admin

from .models import LabResult, LabResultAmendment, LabTest


@admin.register(LabTest)
class LabTestAdmin(admin.ModelAdmin):
    list_display = ("name", "unit", "reference_range", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)


class ReadOnlyAdmin(admin.ModelAdmin):
    """Read-only: results move through the portal workflow so every step is audited."""

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LabResult)
class LabResultAdmin(ReadOnlyAdmin):
    list_display = ("id", "test", "patient", "case", "status", "ordered_at", "released_at", "amended_at")
    list_filter = ("status", "test", "ordered_at")
    search_fields = ("test__name", "patient__user__login_id",
                     "patient__user__first_name", "patient__user__last_name")
    list_select_related = ("test", "patient", "patient__user", "case")


@admin.register(LabResultAmendment)
class LabResultAmendmentAdmin(ReadOnlyAdmin):
    list_display = ("id", "result", "amended_by", "amended_at")
    search_fields = ("result__test__name", "result__patient__user__login_id")
