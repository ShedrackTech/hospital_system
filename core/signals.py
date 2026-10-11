from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.dispatch import receiver

from . import lockout


@receiver(user_login_failed)
def on_login_failed(sender, credentials, request=None, **kwargs):
    identifier = (credentials or {}).get("username") or ""
    if identifier:
        lockout.record_failure(identifier, request)


@receiver(user_logged_in)
def on_login_success(sender, request, user, **kwargs):
    lockout.record_success(user, request)
