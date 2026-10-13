"""Emails sent by the website app."""
import logging

from django.conf import settings
from django.core.mail import EmailMessage

from .models import SiteInfo

logger = logging.getLogger(__name__)


def send_mail(subject, body, to, reply_to=None):
    EmailMessage(
        subject=subject,
        body=body,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        to=to,
        reply_to=reply_to or [],
    ).send(fail_silently=False)


def notify_new_contact_message(message):
    """Email the hospital that a contact message arrived.

    Never raises: the message is already saved, and a mail problem must not
    make the visitor's form fail. Failures are logged instead.
    """
    recipient = SiteInfo.get().notify_email
    if not recipient:
        return False
    lines = [
        "A new message was sent from the website contact form.",
        "",
        f"Type: {message.get_reason_display()}",
        f"From: {message.name} <{message.email}>",
    ]
    if message.social_handle:
        lines.append(f"Social handle: {message.social_handle}")
    lines += ["", message.message, "", "Read and mark it handled in the portal under Website > Messages."]
    try:
        send_mail(
            subject=f"[Website] {message.subject}"[:200],
            body="\n".join(lines),
            to=[recipient],
            reply_to=[message.email],
        )
    except Exception:  # noqa: BLE001 - see docstring
        logger.exception("Could not email contact message %s", message.pk)
        return False
    return True
