"""
Write audit entries:

    from core.audit import log
    log(request.user, "case_viewed", case, patient=case.patient, request=request)

The entry is written in the caller's database transaction. If it cannot be
written, the action fails too (no unlogged changes to patient data).
"""
from .models import AuditLog


def _actor_label(actor):
    if actor is None or not getattr(actor, "pk", None):
        return ""
    name = actor.get_full_name() or actor.get_username()
    ident = getattr(actor, "login_id", "") or actor.get_username()
    return f"{name} ({ident})"[:200]


def log(actor, action, target=None, *, patient=None, detail="", request=None):
    if actor is not None and not getattr(actor, "pk", None):
        actor = None  # AnonymousUser

    target_type, target_id, target_repr = "", None, ""
    if target is not None:
        target_type = target._meta.label_lower
        target_id = target.pk
        target_repr = str(target)[:200]

    ip = None
    if request is not None:
        ip = request.META.get("REMOTE_ADDR") or None

    return AuditLog.objects.create(
        actor=actor,
        actor_label=_actor_label(actor),
        action=action,
        target_type=target_type,
        target_id=target_id,
        target_repr=target_repr,
        patient=patient,
        detail=(detail or "")[:300],
        ip_address=ip,
    )
