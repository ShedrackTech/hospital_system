from datetime import datetime, time, timedelta

from django import template
from django.utils import timezone

from appointments import permissions
from appointments.models import Appointment

register = template.Library()


def _user(context):
    user = context.get("user")
    if user is None:
        user = getattr(context.get("request"), "user", None)
    return user


@register.simple_tag(takes_context=True)
def can_open_appointments(context):
    """{% can_open_appointments as ok %}: may this signed-in staff member open the appointments list?"""
    user = _user(context)
    return bool(user is not None and user.is_authenticated and user.role != "patient"
                and permissions.can_open_staff_list(user))


@register.inclusion_tag("appointments/_dashboard_tile.html", takes_context=True)
def appointment_tile(context):
    """The appointments box on the dashboard. Shows only counts and times to staff, never a reason."""
    data = {"show": False}
    user = _user(context)
    if user is None or not user.is_authenticated:
        return data
    now = timezone.now()
    scheduled = Appointment.Status.SCHEDULED
    if user.role == "patient":
        patient = permissions.patient_of(user)
        if patient is None:
            return data
        upcoming = (
            Appointment.objects.filter(patient=patient, status=scheduled, ends_at__gt=now)
            .select_related("doctor").order_by("starts_at")
        )
        data.update(show=True, kind="patient", next=upcoming.first())
        return data
    if not permissions.can_open_staff_list(user):
        return data
    day_start = timezone.make_aware(datetime.combine(timezone.localdate(), time.min))
    qs = permissions.visible_appointments(user).filter(status=scheduled)
    data.update(
        show=True, kind="staff",
        today_count=qs.filter(starts_at__gte=day_start, starts_at__lt=day_start + timedelta(days=1)).count(),
        upcoming_count=qs.filter(starts_at__gte=day_start).count(),
        next=qs.filter(starts_at__gt=now).order_by("starts_at").first(),
    )
    return data
