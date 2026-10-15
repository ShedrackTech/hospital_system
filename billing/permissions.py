from cases.permissions import is_admin
from core.mixins import is_front_desk

from .models import Invoice


def patient_of(user):
    """The Patient record of a patient account, or None."""
    if getattr(user, "role", "") != "patient":
        return None
    return getattr(user, "patient_profile", None)


def is_cashier(user):
    """Front desk (administrative staff and admin roles) handles money. Patients never do."""
    return user.is_authenticated and user.role != "patient" and is_front_desk(user)


def can_manage_prices(user):
    return user.is_authenticated and user.role != "patient" and is_admin(user)


def is_own_patient(user, invoice):
    patient = patient_of(user)
    return patient is not None and invoice.patient_id == patient.pk


def can_view(user, invoice):
    return is_own_patient(user, invoice) or is_cashier(user)


def can_open_staff_list(user):
    return is_cashier(user)


def visible_invoices(user):
    qs = Invoice.objects.select_related("patient__user", "case")
    patient = patient_of(user)
    if patient is not None:
        return qs.filter(patient=patient)
    if is_cashier(user):
        return qs
    return qs.none()


def payment_problem(user, invoice):
    """A message saying why this user cannot record a payment now, or an empty string when allowed."""
    if not is_cashier(user):
        return "You cannot record payments."
    if invoice.status == Invoice.Status.VOID:
        return "This invoice is void."
    if invoice.status == Invoice.Status.PAID:
        return "This invoice is already paid."
    return ""


def void_problem(user, invoice):
    if not can_manage_prices(user):
        return "Only an administrator can void an invoice."
    if invoice.status == Invoice.Status.VOID:
        return "This invoice is already void."
    if invoice.amount_paid > 0:
        return "An invoice with payments cannot be voided."
    return ""


def can_record_payment(user, invoice):
    return not payment_problem(user, invoice)


def can_void(user, invoice):
    return not void_problem(user, invoice)
