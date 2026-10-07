from django.contrib import admin, messages
from django.db.models import Count
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

from .models import Allergy, CardRenewal, Family, MedicalHistory, Patient


class AllergyInline(admin.TabularInline):
    model = Allergy
    extra = 0


class MedicalHistoryInline(admin.TabularInline):
    model = MedicalHistory
    extra = 0
    readonly_fields = ("recorded_by", "created_at")


class FamilyMemberInline(admin.TabularInline):
    model = Patient
    extra = 0
    can_delete = False
    fields = ("user", "relationship")
    readonly_fields = ("user",)
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Family)
class FamilyAdmin(admin.ModelAdmin):
    list_display = ("family_number", "name", "head_name", "member_count")
    search_fields = (
        "family_number",
        "name",
        "members__user__login_id",
        "members__user__first_name",
        "members__user__last_name",
    )
    readonly_fields = ("family_number", "created_at")
    inlines = [FamilyMemberInline]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_members=Count("members"))

    @admin.display(description="Head")
    def head_name(self, obj):
        head = obj.head
        return head.user.get_full_name() if head else "-"

    @admin.display(description="Members", ordering="_members")
    def member_count(self, obj):
        return obj._members


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = (
        "card_number",
        "full_name",
        "gender",
        "date_of_birth",
        "phone",
        "family",
    )
    list_filter = ("gender", "blood_group")
    search_fields = (
        "user__login_id",
        "user__first_name",
        "user__last_name",
        "user__phone",
        "family__family_number",
    )
    list_select_related = ("user", "family")
    inlines = [AllergyInline, MedicalHistoryInline]

    @admin.display(description="Card number", ordering="user__login_id")
    def card_number(self, obj):
        return obj.card_number

    @admin.display(description="Name")
    def full_name(self, obj):
        return obj.user.get_full_name() or obj.user.username

    @admin.display(description="Phone")
    def phone(self, obj):
        return obj.user.phone

    def add_view(self, request, form_url="", extra_context=None):
        # Patients are registered through the registration form, because it
        # also creates the login account and the card number.
        if not self.has_add_permission(request):
            raise PermissionDenied
        messages.info(
            request,
            "Register the patient here. This creates the login account and card number.",
        )
        return redirect("patients:staff_register")

    def save_formset(self, request, form, formset, change):
        # Record who added each medical history entry
        instances = formset.save(commit=False)
        for obj in instances:
            if isinstance(obj, MedicalHistory) and not obj.recorded_by_id:
                obj.recorded_by = request.user
            obj.save()
        for obj in formset.deleted_objects:
            obj.delete()
        formset.save_m2m()


@admin.register(CardRenewal)
class CardRenewalAdmin(admin.ModelAdmin):
    """A read-only record of every card payment."""

    list_display = (
        "holder",
        "card_type",
        "starts_on",
        "expires_on",
        "amount_charged",
        "received_by",
        "created_at",
    )
    list_filter = ("card_type",)
    search_fields = ("patient__user__login_id", "family__family_number")
    list_select_related = ("patient__user", "family", "card_type", "received_by")

    @admin.display(description="Card holder")
    def holder(self, obj):
        return obj.family or obj.patient

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
