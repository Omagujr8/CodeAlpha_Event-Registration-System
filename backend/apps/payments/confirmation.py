from django.db import transaction
from django.utils import timezone

from rest_framework.exceptions import ValidationError

from apps.events.models import TicketTier
from apps.payments.models import Payment
from apps.payments.services import naira_to_kobo
from apps.registrations.models import Registration
from apps.ticketing.models import TicketHold
from apps.ticketing.ticket_services import issue_ticket
from apps.registrations.email_services import enqueue_registration_confirmation


def mark_payment_refund_required(
    *,
    payment,
    hold,
    verified_data,
    reason,
    expire_hold=False,
):
    """
    Record a successful provider payment that cannot be fulfilled.

    This does not automatically refund the customer.
    It records the payment for a separate refund or manual-resolution
    process.
    """

    if expire_hold and hold.status == TicketHold.Status.ACTIVE:
        hold.status = TicketHold.Status.EXPIRED
        hold.save(update_fields=["status"])

    transaction_id = str(verified_data["id"])

    # Do not violate the unique transaction-ID constraint if the
    # provider transaction ID is already associated with another payment.
    transaction_id_exists = (
        Payment.objects
        .filter(provider_transaction_id=transaction_id)
        .exclude(pk=payment.pk)
        .exists()
    )

    payment.status = Payment.Status.REFUND_REQUIRED

    if not transaction_id_exists:
        payment.provider_transaction_id = transaction_id

    payment.paid_at = timezone.now()

    payment.provider_response = {
        "status": verified_data.get("status"),
        "reference": verified_data.get("reference"),
        "amount": verified_data.get("amount"),
        "currency": verified_data.get("currency"),
        "transaction_id": transaction_id,
        "resolution": "refund_required",
        "resolution_reason": reason,
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

    return None


@transaction.atomic
def confirm_successful_payment(*, payment_reference, verified_data):
    """
    Convert one verified payment into one confirmed registration.

    If payment succeeded but ticket fulfillment is impossible,
    record REFUND_REQUIRED instead.

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

    # Repeated webhook deliveries must not process a payment twice.
    if payment.status in [
        Payment.Status.SUCCESS,
        Payment.Status.REFUND_REQUIRED,
    ]:
        return getattr(payment.hold, "registration", None)

    # Validate the independently verified Paystack response.
    if verified_data.get("reference") != payment.reference:
        raise ValidationError("Payment reference mismatch.")

    if verified_data.get("status") != "success":
        raise ValidationError("Payment has not succeeded.")

    if verified_data.get("amount") != payment.amount_subunit:
        raise ValidationError("Payment amount mismatch.")

    if verified_data.get("currency") != payment.currency:
        raise ValidationError("Payment currency mismatch.")

    transaction_id = verified_data.get("id")

    if transaction_id is None or not str(transaction_id).strip():
        raise ValidationError("Payment transaction ID is missing.")

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

    # Check that the ticket price still matches the payment.
    if ticket_tier.currency != payment.currency:
        raise ValidationError("Ticket currency mismatch.")

    expected_amount = naira_to_kobo(ticket_tier.price * hold.quantity)

    if expected_amount != payment.amount_subunit:
        return mark_payment_refund_required(
            payment=payment,
            hold=hold,
            verified_data=verified_data,
            reason="Ticket price no longer matches the payment.",
        )

    # A successful payment must not be silently discarded because
    # the hold expired or was released.
    if hold.expires_at <= timezone.now():
        return mark_payment_refund_required(
            payment=payment,
            hold=hold,
            verified_data=verified_data,
            reason="Ticket hold expired before fulfillment.",
            expire_hold=True,
        )

    if hold.status != TicketHold.Status.ACTIVE:
        return mark_payment_refund_required(
            payment=payment,
            hold=hold,
            verified_data=verified_data,
            reason="Ticket hold is no longer active.",
        )

    # Check inventory again while holding the database row lock.
    if (
        ticket_tier.sold_quantity + hold.quantity
        > ticket_tier.total_quantity
    ):
        return mark_payment_refund_required(
            payment=payment,
            hold=hold,
            verified_data=verified_data,
            reason="Insufficient ticket inventory for fulfillment.",
        )

    # Prevent a second payment for the same hold from creating
    # another registration.
    if Registration.objects.filter(ticket_hold=hold).exists():
        return mark_payment_refund_required(
            payment=payment,
            hold=hold,
            verified_data=verified_data,
            reason="A registration already exists for this ticket hold.",
        )

    transaction_id = str(transaction_id)

    if (
        Payment.objects
        .filter(provider_transaction_id=transaction_id)
        .exclude(pk=payment.pk)
        .exists()
    ):
        return mark_payment_refund_required(
            payment=payment,
            hold=hold,
            verified_data=verified_data,
            reason="Provider transaction ID is already associated with another payment.",
        )

    registration = Registration.objects.create(
        attendee=hold.attendee,
        event=ticket_tier.event,
        ticket_tier=ticket_tier,
        ticket_hold=hold,
        status=Registration.Status.CONFIRMED,
    )

    issued_tickets = issue_ticket(registration=registration)
    enqueue_registration_confirmation(
        registration=registration,
        tickets=issued_tickets,
    )

    ticket_tier.sold_quantity += hold.quantity
    ticket_tier.save(
        update_fields=["sold_quantity"]
    )

    hold.status = TicketHold.Status.CONVERTED
    hold.save(
        update_fields=["status"]
    )

    payment.status = Payment.Status.SUCCESS
    payment.provider_transaction_id = transaction_id
    payment.paid_at = timezone.now()

    payment.provider_response = {
        "status": verified_data.get("status"),
        "reference": verified_data.get("reference"),
        "amount": verified_data.get("amount"),
        "currency": verified_data.get("currency"),
        "transaction_id": transaction_id,
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