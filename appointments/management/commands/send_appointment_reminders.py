from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from appointments import notices, rules
from appointments.models import Appointment


class Command(BaseCommand):
    help = (
        "Send an in-app reminder to each patient whose scheduled appointment starts within "
        f"{rules.REMINDER_HOURS} hours. Each appointment is reminded once. Run it every day (or more often)."
    )

    def handle(self, *args, **options):
        now = timezone.now()
        due = (
            Appointment.objects.filter(
                status=Appointment.Status.SCHEDULED, starts_at__gt=now,
                starts_at__lte=now + timedelta(hours=rules.REMINDER_HOURS), reminder_sent_at__isnull=True,
            )
            .select_related("patient__user", "doctor")
        )
        sent = 0
        for appt in due:
            with transaction.atomic():
                # Only the run that marks the appointment first sends the reminder, even if two runs overlap
                marked = Appointment.objects.filter(
                    pk=appt.pk, status=Appointment.Status.SCHEDULED, reminder_sent_at__isnull=True,
                ).update(reminder_sent_at=now)
                if marked:
                    notices.reminder(appt)
                    sent += 1
        self.stdout.write(f"Reminders sent: {sent}")
