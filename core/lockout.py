"""
Login lockout.

- 5 wrong passwords in a row for one account block that account for 15 minutes.
- The count is per account: the username and the card number / staff ID of the same
  person share one counter. Unknown IDs are counted and locked the same way, so the
  login page never reveals whether an account exists.
- Failures older than the window are forgotten. A correct login clears the counter.
- Every failure, lock, blocked attempt, success and unlock is written to the audit log.
- An administrator can unlock an account early (accounts/lock_views.py).
"""
import math
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from . import audit
from .models import LoginThrottle

MAX_ATTEMPTS = 5
LOCK_MINUTES = 15
WINDOW_MINUTES = 15
KEEP_DAYS = 1  # unlocked, quiet rows older than this are deleted


def identify(identifier):
    """Returns (key, user_or_None, label) for whatever the person typed."""
    identifier = (identifier or "").strip()[:150]
    user = None
    if identifier:
        User = get_user_model()
        user = User.objects.filter(
            Q(login_id__iexact=identifier) | Q(username__iexact=identifier)
        ).first()
    if user:
        return f"user:{user.pk}", user, str(user)[:200]
    return f"unknown:{identifier.lower()}", None, f"Unknown ID: {identifier}"[:200]


def minutes_left(identifier):
    """0 if the account may try to log in, otherwise the minutes until it may."""
    key, _, _ = identify(identifier)
    now = timezone.now()
    row = LoginThrottle.objects.filter(key=key, locked_until__gt=now).first()
    if row is None:
        return 0
    return max(1, math.ceil((row.locked_until - now).total_seconds() / 60))


def is_locked(identifier):
    return minutes_left(identifier) > 0


def _ip(request):
    return request.META.get("REMOTE_ADDR") if request is not None else None


def record_failure(identifier, request=None):
    key, user, label = identify(identifier)
    now = timezone.now()
    with transaction.atomic():
        row, _ = LoginThrottle.objects.select_for_update().get_or_create(
            key=key, defaults={"label": label, "user": user, "last_failed_at": now}
        )
        if row.locked_until and row.locked_until > now:
            # Already locked: do not extend the lock, just note the attempt
            audit.log(None, "login_blocked", user, detail=label, request=request)
            return row
        if row.locked_until or row.last_failed_at < now - timedelta(minutes=WINDOW_MINUTES):
            row.failed_count = 0          # old failures are forgotten
            row.locked_until = None
        row.failed_count += 1
        row.last_failed_at = now
        row.last_ip = _ip(request)
        row.label, row.user = label, user
        locked = row.failed_count >= MAX_ATTEMPTS
        if locked:
            row.locked_until = now + timedelta(minutes=LOCK_MINUTES)
        row.save()
        audit.log(None, "login_failed", user,
                  detail=f"{label} (attempt {row.failed_count} of {MAX_ATTEMPTS})",
                  request=request)
        if locked:
            audit.log(None, "account_locked", user,
                      detail=f"{label}: locked for {LOCK_MINUTES} minutes", request=request)
    _prune(now)
    return row


def note_blocked(identifier, request=None):
    """A login attempt that was stopped because the account is locked."""
    _, user, label = identify(identifier)
    audit.log(None, "login_blocked", user, detail=label, request=request)


def record_success(user, request=None):
    LoginThrottle.objects.filter(key=f"user:{user.pk}").delete()
    audit.log(user, "login_success", user, request=request)


def unlock(row, actor, request=None):
    with transaction.atomic():
        label = row.label
        row.delete()
        audit.log(actor, "account_unlocked", row.user, detail=label, request=request)


def _prune(now):
    LoginThrottle.objects.filter(
        locked_until__isnull=True, last_failed_at__lt=now - timedelta(days=KEEP_DAYS)
    ).delete()
