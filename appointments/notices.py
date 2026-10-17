"""In-app notifications for appointment events. They never contain the reason for the visit, a cancellation
reason, or any clinical detail. A failure to notify is logged and never undoes the booking or cancellation."""
import logging

from django.urls import reverse
from django.utils import timezone

from notifications import services as notifications

logger = logging.getLogger(__name__)


def _when(appt):
    return timezone.localtime(appt.starts_at).strftime("%a %d %b %Y, %H:%M")


def _doctor_name(appt):
    return appt.doctor.get_full_name() or appt.doctor.get_username()


def _link(appt):
    return reverse("appointments:detail", args=[appt.pk])


def _safe(function, *args):
    try:
        function(*args)
    except Exception:  # the booking or cancellation is already saved, so never fail the request over a notice
        logger.exception("Could not send an appointment notification")


def _booked(appt, actor):
    if actor.pk != appt.patient.user_id:
        notifications.notify(
            appt.patient.user, "appointment_booked", "An appointment was booked for you",
            f"{_when(appt)} with {_doctor_name(appt)}.", _link(appt),
        )
    if actor.pk != appt.doctor_id:
        notifications.notify(
            appt.doctor, "appointment_booked", "A new appointment was booked", f"{_when(appt)}.", _link(appt),
        )


def _cancelled(appt, actor):
    if actor.pk == appt.patient.user_id:
        notifications.notify(
            appt.doctor, "appointment_cancelled", "An appointment was cancelled by the patient",
            f"{_when(appt)}.", _link(appt),
        )
        return
    notifications.notify(
        appt.patient.user, "appointment_cancelled", "Your appointment was cancelled",
        f"The appointment on {_when(appt)} was cancelled by the hospital. Open it for details.", _link(appt),
    )
    if actor.pk != appt.doctor_id:
        notifications.notify(
            appt.doctor, "appointment_cancelled", "An appointment was cancelled", f"{_when(appt)}.", _link(appt),
        )


def _reminder(appt):
    notifications.notify(
        appt.patient.user, "appointment_reminder", "Appointment reminder",
        f"You have an appointment on {_when(appt)} with {_doctor_name(appt)}.", _link(appt),
    )


def booked(appt, actor):
    _safe(_booked, appt, actor)


def cancelled(appt, actor):
    _safe(_cancelled, appt, actor)


def reminder(appt):
    _safe(_reminder, appt)
