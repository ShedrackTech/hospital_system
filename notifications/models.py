from django.conf import settings
from django.db import models


class Notification(models.Model):
    """A short message shown to one person inside the portal.

    Keep it general: no test values, drug names or diagnoses in title or body. The person
    opens the linked page, which applies the normal permission rules, to see the details.
    """

    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=40)  # a short code such as "lab_amended"
    title = models.CharField(max_length=120)
    body = models.CharField(max_length=300, blank=True)
    url = models.CharField(max_length=200, blank=True)  # a path inside the portal, e.g. /laboratory/mine/
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [models.Index(fields=["recipient", "read_at"])]

    def __str__(self):
        return f"{self.title} (to user {self.recipient_id})"

    @property
    def is_read(self):
        return self.read_at is not None
