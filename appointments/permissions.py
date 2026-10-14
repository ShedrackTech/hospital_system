"""Who may see and do what with appointments.

Summary:
- Patient: own appointments only.
- Doctor: appointments booked with them.
- Department head: appointments of their department.
- Front desk (administrative staff and admins): see every appointment's time,
  patient and doctor, but NOT the reason for the visit. They book and cancel.
- Admins: see everything including the reason; may cancel; never record the outcome.
- Everyone else (nurses, support staff, other staff): nothing.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from cases.permissions import is_admin
from core.mixins import is_front_desk

from . import rules
from .models import Appointment

User = get_user_model()

DOCTOR_ROLES = ("doctor", "senior_doctor")


# ---------- who can be booked ----------

def eligible_doctors():
    """Active doctors in the Medical category with a real clinical department.

    The general (triage) department is for walk-ins, and laboratory staff do not
    see patients by appointment, so neither takes bookings.
    """
    return (
        User.objects.filter(
            is_active=True,
            role__in=DOCTOR_ROLES,
            staff_profile__category="medical",
            staff_profile__department__isnull=False,
            staff_profile__department__is_active=True,
            staff_profile__department__is_general=False,
            staff_profile__department__is_laboratory=False,
        )
        .select_related("staff_profile__department")
        .order_by("first_name", "last_name", "username")
    )


def is_eligible_doctor(user):
    return eligible_doctors().filter(pk=user.pk).exists()


# ---------- small identity helpers ----------

def patient_of(user):
    return getattr(user, "patient_profile", None)


def headed_department(user):
    return getattr(user, "headed_department", None)


def is_own_patient(user, appt):
    p = patient_of(user)
    return p is not None and appt.patient_id == p.pk


def is_own_doctor(user, appt):
    return appt.doctor_id == user.pk


def is_head_for(user, appt):
    d = headed_department(user)
    return d is not None and appt.department_id == d.pk


# ---------- viewing ----------

def can_see_reason(user, appt):
    return is_own_patient(user, appt) or is_own_doctor(user, appt) or is_head_for(user, appt) or is_admin(user)


def can_view(user, appt):
    if user.role == "patient":
        return is_own_patient(user, appt)
    return can_see_reason(user, appt) or is_front_desk(user)


def visible_appointments(user):
    qs = Appointment.objects.select_related("patient__user", "doctor", "department")
    if user.role == "patient":
        p = patient_of(user)
        return qs.filter(patient=p) if p else qs.none()
    if is_admin(user) or is_front_desk(user):
        return qs
    q = Q(doctor=user)
    d = headed_department(user)
    if d is not None:
        q |= Q(department=d)
    return qs.filter(q)


def can_open_staff_list(user):
    if user.role == "patient":
        return False
    return is_admin(user) or is_front_desk(user) or headed_department(user) is not None or is_eligible_doctor(user)


# ---------- booking ----------

def can_book_for(user, patient):
    if user.role == "patient":
        own = patient_of(user)
        return own is not None and own.pk == patient.pk
    return is_front_desk(user)


# ---------- cancelling and closing ----------
# Each returns "" when allowed, otherwise a message that can be shown to the user.

def cancel_problem(user, appt, now=None):
    now = now or timezone.now()
    if not can_view(user, appt):
        return "You are not allowed to cancel this appointment."
    if appt.status != Appointment.Status.SCHEDULED:
        return "Only a scheduled appointment can be cancelled."
    if appt.starts_at <= now:
        return "This appointment has already started, so it can no longer be cancelled."
    if is_own_patient(user, appt):
        if appt.starts_at - now < timedelta(hours=rules.PATIENT_CANCEL_HOURS):
            return (
                f"An appointment can only be cancelled online at least {rules.PATIENT_CANCEL_HOURS} "
                "hours before it starts. Please contact the hospital."
            )
        return ""
    if is_front_desk(user) or is_own_doctor(user, appt) or is_head_for(user, appt) or is_admin(user):
        return ""
    return "You are not allowed to cancel this appointment."


def can_cancel(user, appt, now=None):
    return cancel_problem(user, appt, now) == ""


def close_problem(user, appt, now=None):
    """Recording the outcome (completed or no-show) is clinical: the doctor or the head only."""
    now = now or timezone.now()
    if not (is_own_doctor(user, appt) or is_head_for(user, appt)):
        return "You are not allowed to record the outcome of this appointment."
    if appt.status != Appointment.Status.SCHEDULED:
        return "This appointment is already closed."
    if appt.starts_at > now:
        return "The outcome can only be recorded once the appointment time has started."
    return ""


def can_close(user, appt, now=None):
    return close_problem(user, appt, now) == ""


# ---------- availability ----------

def manageable_doctors(user):
    """Doctors whose weekly availability this user may edit."""
    docs = eligible_doctors()
    if user.role == "patient":
        return docs.none()
    if is_admin(user):
        return docs
    q = Q(pk=user.pk)
    d = headed_department(user)
    if d is not None:
        q |= Q(staff_profile__department=d)
    return docs.filter(q)


def can_manage_availability(user, doctor):
    return manageable_doctors(user).filter(pk=doctor.pk).exists()


def can_open_availability(user):
    return is_admin(user) or manageable_doctors(user).exists()
