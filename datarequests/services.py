from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core import audit

from .models import DataRequest

MAX_OPEN_REQUESTS = 5


def create_request(patient, kind, subject, details, request=None):
    subject, details = (subject or "").strip(), (details or "").strip()
    if kind not in dict(DataRequest.Kind.choices):
        raise ValidationError("Choose what you are asking for.")
    if not subject or not details:
        raise ValidationError("Please fill in the subject and the details.")
    with transaction.atomic():
        open_count = DataRequest.objects.filter(patient=patient).exclude(
            status__in=[DataRequest.Status.RESOLVED, DataRequest.Status.DECLINED]
        ).count()
        if open_count >= MAX_OPEN_REQUESTS:
            raise ValidationError(
                f"You already have {open_count} requests being handled. "
                "Please wait for an answer before sending more."
            )
        data_request = DataRequest.objects.create(
            patient=patient, kind=kind, subject=subject[:150], details=details
        )
        audit.log(patient.user, "data_request_created", data_request, patient=patient,
                  detail=data_request.get_kind_display(), request=request)
    return data_request


def update_request(actor, data_request, status, response, request=None):
    """An administrator moves a request along and records the decision."""
    response = (response or "").strip()
    if status not in (DataRequest.Status.IN_REVIEW, DataRequest.Status.RESOLVED,
                      DataRequest.Status.DECLINED):
        raise ValidationError("Choose a valid status.")
    if status in (DataRequest.Status.RESOLVED, DataRequest.Status.DECLINED) and not response:
        raise ValidationError("Write the answer the patient will see before closing a request.")
    with transaction.atomic():
        locked = (
            DataRequest.objects.select_for_update(of=("self",))
            .select_related("patient").get(pk=data_request.pk)
        )
        if locked.is_closed:
            raise ValidationError("This request is already closed.")
        old = locked.status
        locked.status = status
        locked.handled_by = actor
        locked.handled_at = timezone.now()
        if response:
            locked.response = response
        locked.save()
        # The text of the request and of the answer is never copied into the audit log
        audit.log(actor, "data_request_updated", locked, patient=locked.patient,
                  detail=f"{old} -> {status}", request=request)
    return locked
