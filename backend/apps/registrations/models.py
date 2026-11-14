import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.events.models import Event, TicketTier
from apps.ticketing.models import TicketHold


class Registration(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        CONFIRMED = "confirmed", "Confirmed"
        CANCELLED = "cancelled", "Cancelled"

    reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    attendee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="registrations")
    event = models.ForeignKey(Event, on_delete=models.PROTECT, related_name="registrations")
    ticket_tier = models.ForeignKey(TicketTier, on_delete=models.PROTECT, related_name="registrations")
    ticket_hold = models.OneToOneField(TicketHold, on_delete=models.PROTECT, related_name="registration", null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    registered_at = models.DateTimeField(auto_now_add=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-registered_at"]
        constraints = [models.CheckConstraint(condition=Q(status__in=["pending", "confirmed", "cancelled"]), name="registration_status_valid")]
        indexes = [
            models.Index(fields=["attendee", "status"], name="reg_attendee_status_idx"),
            models.Index(fields=["event", "status"], name="reg_event_status_idx"),
        ]

    def __str__(self):
        return f"{self.reference} - {self.attendee.email}"


class EmailOutbox(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    recipient = models.EmailField()
    subject = models.CharField(max_length=255)
    body = models.TextField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["status", "next_attempt_at"], name="email_status_next_idx")]

    def __str__(self):
        return f"{self.recipient}: {self.subject}"
