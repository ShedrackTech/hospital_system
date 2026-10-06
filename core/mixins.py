from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied

from accounts.models import User

# Roles that oversee the whole hospital
ADMIN_ROLES = (User.Role.MAIN_ADMIN, User.Role.SUB_ADMIN)


class StaffRequiredMixin(LoginRequiredMixin):
    """Logged-in staff only. Patients get a 403."""

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.is_patient:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class AdminRequiredMixin(LoginRequiredMixin):
    """Main Admin and Sub Admin only. Everyone else gets a 403."""

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.role not in ADMIN_ROLES:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)
