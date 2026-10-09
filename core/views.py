from django.db.models import Q
from django.views.generic import ListView

from .forms import AuditFilterForm, action_label
from .mixins import AdminRequiredMixin
from .models import AuditLog


class AuditLogListView(AdminRequiredMixin, ListView):
    """Read-only audit log for main admin and sub admin, inside the hospital portal."""

    template_name = "core/audit_list.html"
    context_object_name = "entries"
    paginate_by = 30

    def get_queryset(self):
        self.form = AuditFilterForm(self.request.GET)
        entries = AuditLog.objects.select_related("patient__user")
        if not self.form.is_valid():
            return entries
        data = self.form.cleaned_data

        query = (data.get("q") or "").strip()
        if query:
            entries = entries.filter(
                Q(actor_label__icontains=query)
                | Q(target_repr__icontains=query)
                | Q(detail__icontains=query)
                | Q(patient__user__login_id__icontains=query)
                | Q(patient__user__first_name__icontains=query)
                | Q(patient__user__last_name__icontains=query)
            )
        if data.get("action"):
            entries = entries.filter(action=data["action"])
        if data.get("date_from"):
            entries = entries.filter(created_at__date__gte=data["date_from"])
        if data.get("date_to"):
            entries = entries.filter(created_at__date__lte=data["date_to"])
        return entries

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        entries = list(context["entries"])
        for entry in entries:
            entry.action_label = action_label(entry.action)
        context["entries"] = entries
        context["form"] = self.form
        params = self.request.GET.copy()
        params.pop("page", None)
        context["query_string"] = params.urlencode()
        return context
