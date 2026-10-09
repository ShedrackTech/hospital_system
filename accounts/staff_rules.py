"""Who may manage whom in the staff management pages."""
from core.mixins import ADMIN_ROLES

from .models import User


def can_manage(actor, target):
    """
    - Nobody manages themselves here (no self-demotion or self-lockout).
    - Patients are never managed here.
    - Main admin accounts are never managed through the portal.
    - Only a main admin can manage a sub admin.
    - A sub admin can manage everyone below sub admin.
    """
    if target.pk == actor.pk or target.is_patient:
        return False
    if target.is_superuser or target.role == User.Role.MAIN_ADMIN:
        return False
    if target.role == User.Role.SUB_ADMIN:
        return actor.role == User.Role.MAIN_ADMIN
    return actor.role in ADMIN_ROLES


def assignable_roles(actor):
    """Roles the actor may give to staff. Main admin accounts are never created here."""
    excluded = {User.Role.PATIENT, User.Role.MAIN_ADMIN}
    if actor.role != User.Role.MAIN_ADMIN:
        excluded.add(User.Role.SUB_ADMIN)
    return [(value, label) for value, label in User.Role.choices if value not in excluded]
