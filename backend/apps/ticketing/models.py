import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class TicketHold(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        RELEASED = "released", "Released"
        EXPIRED = "expired", "Expired"
        CONVERTED = "converted", "Converted"

    reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    attendee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ticket_holds")
    ticket_tier = models.ForeignKey("events.TicketTier", on_delete=models.PROTECT, related_name="holds")
    quantity = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name="ticket_hold_quantity_positive"),
            models.CheckConstraint(condition=Q(status__in=["active", "released", "expired", "converted"]), name="ticket_hold_status_valid"),
        ]
        indexes = [
            models.Index(fields=["ticket_tier", "status", "expires_at"], name="hold_tier_status_exp_idx"),
            models.Index(fields=["attendee", "status"], name="hold_attendee_status_idx"),
        ]

    def __str__(self):
        return f"{self.reference} - {self.ticket_tier.name}"


class IssuedTicket(models.Model):
    class Status(models.TextChoices):
        ISSUED = "issued", "Issued"
        CHECKED_IN = "checked_in", "Checked in"
        REVOKED = "revoked", "Revoked"

    reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    registration = models.OneToOneField("registrations.Registration", on_delete=models.PROTECT, related_name="ticket")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ISSUED, db_index=True)
    issued_at = models.DateTimeField(auto_now_add=True)
    checked_in_at = models.DateTimeField(null=True, blank=True)
    checked_in_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="ticket_checkins")

    class Meta:
        ordering = ["-issued_at"]
        indexes = [models.Index(fields=["registration", "status"], name="ticket_reg_status_idx")]

    def __str__(self):
        return f"Ticket {self.reference}"
