from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.core.exceptions import PermissionDenied
from django.db.models import Q

UserModel = get_user_model()


class LoginIDBackend(ModelBackend):
    """Log in with a card number / staff ID (login_id) or a username."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)
        if not username or password is None:
            return None

        username = username.strip()

        # A locked account cannot log in, even with the right password. Raising
        # PermissionDenied stops every other login method too (portal and Django admin).
        from core import lockout

        if lockout.is_locked(username):
            raise PermissionDenied

        try:
            user = UserModel.objects.get(
                Q(login_id__iexact=username) | Q(username__iexact=username)
            )
        except UserModel.DoesNotExist:
            # Run the hasher once to reduce timing differences
            UserModel().set_password(password)
            return None
        except UserModel.MultipleObjectsReturned:
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
