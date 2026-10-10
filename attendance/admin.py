from django.contrib import admin

from .models import AttendanceCorrection, AttendanceRecord, RosterEntry, ShiftType


class CorrectionInline(admin.TabularInline):
    model = AttendanceCorrection
    extra = 0
    can_delete = False
    readonly_fields = ("corrected_by", "reason", "old_clock_in", "old_clock_out",
                       "new_clock_in", "new_clock_out", "created_at")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    """Read-only: records change only through the portal so every change is audited."""

    list_display = ("user", "work_date", "clock_in", "clock_out", "source", "confirmed_by")
    list_filter = ("source", "work_date")
    search_fields = ("user__first_name", "user__last_name", "user__login_id")
    list_select_related = ("user", "confirmed_by")
    date_hierarchy = "work_date"
    inlines = [CorrectionInline]

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ShiftType)
class ShiftTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "start_time", "end_time", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.register(RosterEntry)
class RosterEntryAdmin(admin.ModelAdmin):
    list_display = ("user", "date", "shift", "building", "created_by")
    list_filter = ("date", "shift", "building")
    search_fields = ("user__first_name", "user__last_name", "user__login_id")
    list_select_related = ("user", "shift", "building")
    date_hierarchy = "date"
