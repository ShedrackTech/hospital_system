from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from core import audit

from . import ward_permissions as perms
from .models import WardAssignment


def assign_nurses(actor, nurses, ward, request=None):
    """Assign each nurse to the ward. Returns how many new assignments were made."""
    nurses = list(nurses)
    if not nurses:
        raise ValidationError("Choose at least one nurse.")
    allowed = set(perms.manageable_nurses(actor).values_list("pk", flat=True))
    if any(nurse.pk not in allowed for nurse in nurses):
        raise PermissionDenied
    created = 0
    with transaction.atomic():
        for nurse in nurses:
            _, was_created = WardAssignment.objects.get_or_create(
                user=nurse, ward=ward, defaults={"created_by": actor}
            )
            created += was_created
            if was_created:
                audit.log(actor, "ward_staff_assigned", ward,
                          detail=f"{nurse} assigned to {ward}", request=request)
    return created


def remove_assignment(actor, assignment, request=None):
    if not perms.manageable_nurses(actor).filter(pk=assignment.user_id).exists():
        raise PermissionDenied
    with transaction.atomic():
        detail = f"{assignment.user} removed from {assignment.ward}"
        ward = assignment.ward
        assignment.delete()
        audit.log(actor, "ward_staff_removed", ward, detail=detail, request=request)
