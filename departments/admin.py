from django.contrib import admin
from django.db.models import Count

from .models import Department, StaffProfile


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "head", "is_general", "is_active", "staff_count")
    list_filter = ("is_general", "is_active")
    search_fields = ("name", "description", "head__username", "head__login_id")
    list_select_related = ("head",)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_staff_count=Count("staff"))

    @admin.display(description="Staff", ordering="_staff_count")
    def staff_count(self, obj):
        return obj._staff_count


@admin.register(StaffProfile)
class StaffProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "category", "job_title", "department", "grade")
    list_filter = ("category", "grade", "department")
    search_fields = (
        "user__login_id",
        "user__username",
        "user__first_name",
        "user__last_name",
        "job_title",
    )
    list_select_related = ("user", "department")