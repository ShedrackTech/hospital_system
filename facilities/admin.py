from django.contrib import admin
from django.db.models import Count, Q

from .models import Admission, Bed, Building, Ward, WardAssignment


class BedInline(admin.TabularInline):
    model = Bed
    extra = 0


@admin.register(Building)
class BuildingAdmin(admin.ModelAdmin):
    list_display = ("name", "ward_count")
    search_fields = ("name", "description")

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_ward_count=Count("wards"))

    @admin.display(description="Wards", ordering="_ward_count")
    def ward_count(self, obj):
        return obj._ward_count


@admin.register(Ward)
class WardAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "building",
        "ward_type",
        "floor",
        "department",
        "total_beds",
        "occupied_beds",
    )
    list_filter = ("ward_type", "building", "department")
    search_fields = ("name", "building__name")
    list_select_related = ("building", "department")
    inlines = [BedInline]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _total=Count("beds"),
            _occupied=Count("beds", filter=Q(beds__is_occupied=True)),
        )

    @admin.display(description="Beds", ordering="_total")
    def total_beds(self, obj):
        return obj._total

    @admin.display(description="Occupied", ordering="_occupied")
    def occupied_beds(self, obj):
        return obj._occupied


@admin.register(Bed)
class BedAdmin(admin.ModelAdmin):
    list_display = ("ward", "number", "is_occupied")
    list_filter = ("is_occupied", "ward__building", "ward")
    search_fields = ("number", "ward__name", "ward__building__name")
    list_select_related = ("ward", "ward__building")


@admin.register(Admission)
class AdmissionAdmin(admin.ModelAdmin):
    """Read-only history: admit and discharge from the case page so beds stay in sync."""

    list_display = ("case", "bed", "admitted_by", "admitted_at", "discharged_at")
    list_filter = ("discharged_at", "bed__ward__building", "bed__ward")
    search_fields = ("case__patient__user__first_name", "case__patient__user__last_name",
                     "case__patient__user__login_id", "bed__number", "bed__ward__name")
    list_select_related = ("case", "bed", "bed__ward", "admitted_by")
    readonly_fields = ("case", "bed", "admitted_by", "admitted_at",
                       "discharged_by", "discharged_at")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(WardAssignment)
class WardAssignmentAdmin(admin.ModelAdmin):
    list_display = ("user", "ward", "created_by", "created_at")
    list_filter = ("ward__building", "ward")
    search_fields = ("user__first_name", "user__last_name", "user__login_id", "ward__name")
    list_select_related = ("user", "ward", "ward__building")
