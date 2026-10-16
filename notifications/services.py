"""Other apps call notify() or notify_many(). Only the owner can read or mark their notifications."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from .models import Notification


def clean_url(url):
    """Allow only a path inside this site (starts with one slash). Blocks other sites and odd characters."""
    url = (url or "").strip()
    if not url:
        return ""
    if len(url) > 200 or not url.startswith("/") or url.startswith("//") or "\\" in url:
        raise ValidationError("A notification link must be a path inside the portal.")
    if any(ord(ch) < 32 for ch in url):
        raise ValidationError("A notification link must be a path inside the portal.")
    return url


def notify(recipient, kind, title, body="", url=""):
    """Create one notification. Returns None for an inactive account."""
    title = (title or "").strip()
    if not title:
        raise ValidationError("A notification needs a title.")
    if not recipient.is_active:
        return None
    return Notification.objects.create(
        recipient=recipient, kind=(kind or "")[:40], title=title[:120],
        body=(body or "").strip()[:300], url=clean_url(url),
    )


def notify_many(recipients, kind, title, body="", url=""):
    seen, created = set(), []
    for recipient in recipients:
        if recipient.pk in seen:
            continue
        seen.add(recipient.pk)
        notification = notify(recipient, kind, title, body, url)
        if notification is not None:
            created.append(notification)
    return created


def mark_read(notification, actor):
    if notification.recipient_id != actor.pk:
        raise PermissionDenied
    Notification.objects.filter(pk=notification.pk, read_at__isnull=True).update(read_at=timezone.now())
    notification.refresh_from_db()
    return notification


def mark_all_read(actor):
    return Notification.objects.filter(recipient=actor, read_at__isnull=True).update(read_at=timezone.now())


def unread_count(user):
    if not user.is_authenticated:
        return 0
    return Notification.objects.filter(recipient=user, read_at__isnull=True).count()
