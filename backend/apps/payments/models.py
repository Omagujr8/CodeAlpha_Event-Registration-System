import uuid

from django.db import models

from apps.ticketing.models import TicketHold


class Payment(models.Model):
    class Status(models.TextChoices):
        INITIALIZED = "initialized", "Initialized"
        PENDING = "pending", "Pending"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        ABANDONED = "abandoned", "Abandoned"

    reference = models.CharField(
        max_length=100,
        unique=True,
        default=lambda: uuid.uuid4().hex,
        editable=False,
    )
    hold = models.ForeignKey(
        TicketHold,
        on_delete=models.PROTECT,
        related_name="payments",
    )
    amount_subunit = models.PositiveBigIntegerField()
    currency = models.CharField(max_length=3, default="NGN")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.INITIALIZED,
        db_index=True,
    )
    authorization_url = models.URLField(max_length=500, blank=True)
    access_code = models.CharField(max_length=100, blank=True)
    provider_transaction_id = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        unique=True,
    )
    provider_response = models.JSONField(default=dict, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["hold", "status"],
                name="payment_hold_status_idx",
            ),
        ]

    def __str__(self):
        return f"{self.reference} - {self.status}"