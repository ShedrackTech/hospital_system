from django.contrib import admin

from .models import Dispensing, Drug, Prescription, PrescriptionItem, StockAdjustment, StockBatch


class ReadOnlyAdmin(admin.ModelAdmin):
    """Read-only: these records change only through the portal workflow, so every step is audited."""

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Drug)
class DrugAdmin(admin.ModelAdmin):
    list_display = ("name", "strength", "form", "drug_class", "reorder_level", "is_active")
    list_filter = ("form", "is_active")
    search_fields = ("name", "ingredients", "drug_class")


@admin.register(StockBatch)
class StockBatchAdmin(ReadOnlyAdmin):
    list_display = ("drug", "batch_number", "expiry_date", "quantity_received", "quantity_remaining")
    list_filter = ("expiry_date",)
    search_fields = ("drug__name", "batch_number")
    list_select_related = ("drug",)


@admin.register(StockAdjustment)
class StockAdjustmentAdmin(ReadOnlyAdmin):
    list_display = ("batch", "change", "reason", "adjusted_by", "adjusted_at")
    list_filter = ("reason",)


@admin.register(Prescription)
class PrescriptionAdmin(ReadOnlyAdmin):
    list_display = ("id", "patient", "case", "status", "prescribed_by", "prescribed_at")
    list_filter = ("status", "prescribed_at")
    search_fields = ("patient__user__login_id", "patient__user__first_name", "patient__user__last_name")
    list_select_related = ("patient", "patient__user", "case")


@admin.register(PrescriptionItem)
class PrescriptionItemAdmin(ReadOnlyAdmin):
    list_display = ("prescription", "drug", "quantity", "quantity_dispensed")
    list_select_related = ("prescription", "drug")


@admin.register(Dispensing)
class DispensingAdmin(ReadOnlyAdmin):
    list_display = ("item", "batch", "quantity", "dispensed_by", "dispensed_at")
    list_select_related = ("item", "batch", "dispensed_by")
