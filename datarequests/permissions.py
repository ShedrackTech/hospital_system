"""Who may read and answer patient data requests."""
from cases import permissions as case_perms


def is_records_officer(user):
    profile = getattr(user, "staff_profile", None)
    return bool(profile and profile.records_officer)


def can_handle(user):
    """Admin roles, and staff marked as records officers on their staff profile."""
    return bool(
        user.is_authenticated and not user.is_patient
        and (case_perms.is_admin(user) or is_records_officer(user))
    )
