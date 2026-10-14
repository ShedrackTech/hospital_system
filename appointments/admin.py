from django.contrib import admin

from .models import Appointment, DoctorAvailability


@admin.register(DoctorAvailability)
class DoctorAvailabilityAdmin(admin.ModelAdmin):
    list_display = ("doctor", "weekday", "start_time", "end_time", "slot_minutes")
    list_filter = ("weekday",)
    search_fields = ("doctor__username", "doctor__first_name", "doctor__last_name")


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    # Backup only: everyday work is done in the portal. The reason for the visit
    # is medical information, so it is kept out of the list and search.
    list_display = ("patient", "doctor", "department", "starts_at", "status")
    list_filter = ("status", "department")
    search_fields = ("patient__user__username", "patient__user__first_name", "patient__user__last_name",
                     "doctor__username", "doctor__first_name", "doctor__last_name")
    date_hierarchy = "starts_at"
