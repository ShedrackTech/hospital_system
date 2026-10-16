from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import services
from .models import Notification


@login_required
def notification_list(request):
    rows = list(Notification.objects.filter(recipient=request.user)[:100])
    return render(request, "notifications/list.html", {
        "rows": rows, "unread": sum(1 for n in rows if not n.is_read),
    })


@login_required
@require_POST
def open_notification(request, pk):
    # Someone else's notification gives 404, so its existence is not revealed.
    notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
    services.mark_read(notification, request.user)
    target = notification.url
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts=None):
        return redirect(target)
    return redirect("notifications:list")


@login_required
@require_POST
def mark_all(request):
    count = services.mark_all_read(request.user)
    if count:
        messages.success(request, "All notifications are marked as read.")
    return redirect("notifications:list")
