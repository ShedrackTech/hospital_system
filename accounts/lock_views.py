from datetime import timedelta

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views import View
from django.views.generic import ListView

from core import lockout
from core.mixins import AdminRequiredMixin
from core.models import LoginThrottle


class LockedAccountsView(AdminRequiredMixin, ListView):
    """Accounts that are locked now, and accounts with recent failed attempts."""

    template_name = "accounts/locked_list.html"
    context_object_name = "locks"

    def get_queryset(self):
        return LoginThrottle.objects.filter(locked_until__gt=timezone.now()).order_by("locked_until")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        now = timezone.now()
        context["watching"] = LoginThrottle.objects.filter(
            failed_count__gt=0, locked_until__isnull=True,
            last_failed_at__gte=now - timedelta(minutes=lockout.WINDOW_MINUTES),
        )
        context["max_attempts"] = lockout.MAX_ATTEMPTS
        return context


class UnlockView(AdminRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        row = get_object_or_404(LoginThrottle, pk=pk)
        lockout.unlock(row, request.user, request)
        messages.success(request, f"{row.label} can log in again.")
        return redirect("accounts:locked_list")
