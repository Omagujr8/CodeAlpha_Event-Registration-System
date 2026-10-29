
from django.conf import settings
from django.db import models
from django.db.models import Q


class Event(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        CANCELLED = "cancelled", "Cancelled"

    organizer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="organized_events",
    )
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True)
    description = models.TextField()
    venue = models.CharField(max_length=255)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["starts_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_at__gt=models.F("starts_at")),
                name="event_end_after_start",
            ),
        ]

    def __str__(self):
        return self.title


class TicketTier(models.Model):
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name="ticket_tiers",
    )
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default="NGN")
    total_quantity = models.PositiveIntegerField()
    sold_quantity = models.PositiveIntegerField(default=0)
    sales_start = models.DateTimeField(null=True, blank=True)
    sales_end = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["price"]
        constraints = [
            models.CheckConstraint(
                condition=Q(price__gte=0),
                name="ticket_tier_price_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(
                    sold_quantity__lte=models.F("total_quantity")
                ),
                name="ticket_sold_not_over_total",
            ),
            models.CheckConstraint(
                condition=(
                    Q(sales_end__isnull=True)
                    | Q(sales_start__isnull=True)
                    | Q(sales_end__gt=models.F("sales_start"))
                ),
                name="ticket_sales_end_after_start",
            ),
        ]

    def __str__(self):
        return f"{self.event.title} - {self.name}"

    @property
    def remaining_quantity(self):
        return self.total_quantity - self.sold_quantity
