from django.contrib import admin

from .models import Case, CaseEvent


class CaseEventInline(admin.TabularInline):
    model = CaseEvent
    extra = 0
    can_delete = False
    readonly_fields = ("actor", "action", "note", "created_at")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Case)
class CaseAdmin(admin.ModelAdmin):
    list_display = ("id", "patient", "department", "assigned_to", "status",
                    "routed_at", "created_at")
    list_filter = ("status", "department", "created_at")
    search_fields = ("complaint", "patient__user__username",
                     "assigned_to__username")
    readonly_fields = ("created_at", "updated_at", "routed_by", "routed_at")
    inlines = [CaseEventInline]


@admin.register(CaseEvent)
class CaseEventAdmin(admin.ModelAdmin):
    list_display = ("case", "action", "actor", "created_at")
    list_filter = ("action", "created_at")
    search_fields = ("note", "actor__username")
