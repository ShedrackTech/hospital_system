from django.contrib import admin

from .models import ChargeItem, Invoice, InvoiceLine, Payment


class ReadOnlyAdmin(admin.ModelAdmin):
    """Money records are append-only: look here, change them through the portal."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ChargeItem)
class ChargeItemAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "unit_price", "is_active")
    search_fields = ("name",)
    list_filter = ("category", "is_active")


class InvoiceLineInline(admin.TabularInline):
    model = InvoiceLine
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Invoice)
class InvoiceAdmin(ReadOnlyAdmin):
    list_display = ("number", "patient", "status", "total", "amount_paid", "issued_by", "issued_at")
    search_fields = ("number", "patient__user__login_id")
    list_filter = ("status",)
    inlines = [InvoiceLineInline]


@admin.register(Payment)
class PaymentAdmin(ReadOnlyAdmin):
    list_display = ("receipt_number", "invoice", "amount", "method", "received_by", "received_at")
    search_fields = ("receipt_number", "invoice__number", "reference")
    list_filter = ("method",)
