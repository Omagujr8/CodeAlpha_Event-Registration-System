from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.events.models import TicketTier
from apps.payments.models import Payment
from apps.registrations.models import Registration
from apps.ticketing.models import TicketHold


@transaction.atomic
def confirm_successful_payment(*, payment_reference, verified_data):
    """
    Convert one verified payment into one confirmed registration.

    All database changes happen in one transaction.
    """

    try:
        payment = (
            Payment.objects
            .select_for_update()
            .select_related("hold")
            .get(reference=payment_reference)
        )
    except Payment.DoesNotExist:
        raise ValidationError("Payment does not exist.")

    # Repeated webhook deliveries must not create another registration.
    if payment.status == Payment.Status.SUCCESS:
        return getattr(payment.hold, "registration", None)

    hold = (
        TicketHold.objects
        .select_for_update()
        .get(pk=payment.hold_id)
    )

    ticket_tier = (
        TicketTier.objects
        .select_for_update()
        .get(pk=hold.ticket_tier_id)
    )

    # Verify the data again at the confirmation boundary.
    if verified_data.get("reference") != payment.reference:
        raise ValidationError("Payment reference mismatch.")

    if verified_data.get("status") != "success":
        raise ValidationError("Payment has not succeeded.")

    if verified_data.get("amount") != payment.amount_subunit:
        raise ValidationError("Payment amount mismatch.")

    if verified_data.get("currency") != payment.currency:
        raise ValidationError("Payment currency mismatch.")

    if hold.status != TicketHold.Status.ACTIVE:
        raise ValidationError("Ticket hold is no longer active.")

    if hold.expires_at <= timezone.now():
        raise ValidationError("Ticket hold has expired.")

    if ticket_tier.currency != payment.currency:
        raise ValidationError("Ticket currency mismatch.")

    expected_amount = int(
        ticket_tier.price * hold.quantity * 100
    )

    if expected_amount != payment.amount_subunit:
        raise ValidationError("Ticket price has changed.")

    if ticket_tier.sold_quantity + hold.quantity > ticket_tier.total_quantity:
        raise ValidationError("Insufficient ticket inventory.")

    # The OneToOneField on Registration also prevents duplicate
    # registrations for the same hold at the database level.
    registration = Registration.objects.create(
        attendee=hold.attendee,
        event=ticket_tier.event,
        ticket_tier=ticket_tier,
        ticket_hold=hold,
        status=Registration.Status.CONFIRMED,
    )

    ticket_tier.sold_quantity += hold.quantity
    ticket_tier.save(update_fields=["sold_quantity"])

    hold.status = TicketHold.Status.CONVERTED
    hold.save(update_fields=["status"])

    payment.status = Payment.Status.SUCCESS
    payment.provider_transaction_id = str(verified_data["id"])
    payment.paid_at = timezone.now()
    payment.provider_response = {
        "status": verified_data.get("status"),
        "reference": verified_data.get("reference"),
        "amount": verified_data.get("amount"),
        "currency": verified_data.get("currency"),
        "transaction_id": str(verified_data.get("id")),
    }
    payment.save(
        update_fields=[
            "status",
            "provider_transaction_id",
            "paid_at",
            "provider_response",
            "updated_at",
        ]
    )

    return registration