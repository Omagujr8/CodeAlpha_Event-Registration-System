from datetime import timedelta

import redis

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import APIException

from apps.events.models import TicketTier
from apps.ticketing.models import TicketHold
from apps.ticketing.redis_client import redis_client


class InventoryUnavailable(APIException):
    status_code = 503
    default_detail = "Ticket reservation is temporarily unavailable."
    default_code = "inventory_unavailable"


def get_hold_redis_key(reference):
    return f"ticket_hold:{reference}"


def create_ticket_hold(*, attendee, ticket_tier_id, quantity):
    if quantity < 1:
        raise ValidationError(
            {"quantity": "Quantity must be at least 1."}
        )

    now = timezone.now()

    try:
        with transaction.atomic():
            # Lock the ticket tier so simultaneous requests cannot
            # reserve the same remaining inventory.
            try:
                ticket_tier = (
                    TicketTier.objects
                    .select_for_update()
                    .select_related("event")
                    .get(pk=ticket_tier_id)
                )
            except TicketTier.DoesNotExist:
                raise ValidationError(
                    {"ticket_tier": "Ticket tier does not exist."}
                )

            event = ticket_tier.event

            if event.status != event.Status.PUBLISHED:
                raise ValidationError(
                    {"ticket_tier": "This event is not available."}
                )

            if not ticket_tier.is_active:
                raise ValidationError(
                    {"ticket_tier": "This ticket tier is inactive."}
                )

            if (
                ticket_tier.sales_start
                and now < ticket_tier.sales_start
            ):
                raise ValidationError(
                    {"ticket_tier": "Ticket sales have not started."}
                )

            if (
                ticket_tier.sales_end
                and now >= ticket_tier.sales_end
            ):
                raise ValidationError(
                    {"ticket_tier": "Ticket sales have ended."}
                )

            # Only active holds that have not expired count toward
            # reserved inventory.
            active_holds = TicketHold.objects.filter(
                ticket_tier=ticket_tier,
                status=TicketHold.Status.ACTIVE,
                expires_at__gt=now,
            ).aggregate(
                reserved=Sum("quantity")
            )["reserved"] or 0

            available = (
                ticket_tier.total_quantity
                - ticket_tier.sold_quantity
                - active_holds
            )

            if quantity > available:
                raise ValidationError(
                    {
                        "quantity": (
                            f"Only {available} ticket(s) are available."
                        )
                    }
                )

            expires_at = now + timedelta(
                seconds=settings.TICKET_HOLD_DURATION_SECONDS
            )

            hold = TicketHold.objects.create(
                attendee=attendee,
                ticket_tier=ticket_tier,
                quantity=quantity,
                expires_at=expires_at,
            )

            # Redis provides the temporary TTL for this hold.
            # If Redis fails, the database transaction rolls back.
            redis_key = get_hold_redis_key(hold.reference)

            redis_created = redis_client.set(
                redis_key,
                "active",
                ex=settings.TICKET_HOLD_DURATION_SECONDS,
                nx=True,
            )

            if not redis_created:
                raise InventoryUnavailable(
                    "Could not create the temporary ticket hold."
                )

            return hold

    except redis.RedisError as exc:
        raise InventoryUnavailable() from exc


def expire_hold_if_needed(hold):
    """Update the database status when a hold's expiry has passed."""
    if (
        hold.status == TicketHold.Status.ACTIVE
        and hold.expires_at <= timezone.now()
    ):
        hold.status = TicketHold.Status.EXPIRED
        hold.save(update_fields=["status"])

    return hold


def release_ticket_hold(*, hold, attendee):
    with transaction.atomic():
        locked_hold = (
            TicketHold.objects
            .select_for_update()
            .get(pk=hold.pk)
        )

        if locked_hold.attendee_id != attendee.id:
            raise ValidationError(
                {"detail": "You cannot release another user's hold."}
            )

        if locked_hold.status != TicketHold.Status.ACTIVE:
            raise ValidationError(
                {"detail": "This hold is no longer active."}
            )

        if locked_hold.expires_at <= timezone.now():
            locked_hold.status = TicketHold.Status.EXPIRED
        else:
            locked_hold.status = TicketHold.Status.RELEASED

        locked_hold.save(update_fields=["status"])

        reference = locked_hold.reference

    # Redis TTL is a fallback; explicit release also removes the key.
    try:
        redis_client.delete(get_hold_redis_key(reference))
    except redis.RedisError:
        pass

    return locked_hold