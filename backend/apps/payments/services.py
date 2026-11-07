import requests

from decimal import Decimal, ROUND_HALF_UP
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, ValidationError

from apps.payments.models import Payment
from apps.ticketing.models import TicketHold


class PaystackUnavailable(APIException):
    status_code = 503
    default_detail = "Payment service is temporarily unavailable."
    default_code = "payment_service_unavailable"


def naira_to_kobo(amount):
    """Convert a naira Decimal amount into an integer number of kobo."""
    amount = Decimal(amount)
    kobo = (amount * Decimal("100")).quantize(
        Decimal("1"),
        rounding=ROUND_HALF_UP,
    )
    return int(kobo)


def initialize_paystack_payment(*, hold_reference, attendee):
    if not settings.PAYSTACK_SECRET_KEY:
        raise PaystackUnavailable(
            "Paystack has not been configured on the server."
        )

    # Lock and validate the hold before creating a payment attempt.
    with transaction.atomic():
        try:
            hold = (
                TicketHold.objects
                .select_for_update()
                .select_related("ticket_tier", "ticket_tier__event")
                .get(reference=hold_reference)
            )
        except TicketHold.DoesNotExist:
            raise ValidationError(
                {"hold_reference": "Ticket hold does not exist."}
            )

        if hold.attendee_id != attendee.id:
            raise ValidationError(
                {"hold_reference": "This hold does not belong to you."}
            )

        if hold.status != TicketHold.Status.ACTIVE:
            raise ValidationError(
                {"hold_reference": "This ticket hold is no longer active."}
            )

        if hold.expires_at <= timezone.now():
            hold.status = TicketHold.Status.EXPIRED
            hold.save(update_fields=["status"])
            raise ValidationError(
                {"hold_reference": "This ticket hold has expired."}
            )

        ticket_tier = hold.ticket_tier

        if ticket_tier.currency != "NGN":
            raise ValidationError(
                {"currency": "Only NGN payments are currently supported."}
            )

        amount = ticket_tier.price * hold.quantity
        amount_subunit = naira_to_kobo(amount)

        if amount_subunit <= 0:
            raise ValidationError(
                {"amount": "The payment amount must be greater than zero."}
            )

        # Prevent another payment attempt if this hold is already paid.
        if Payment.objects.filter(
            hold=hold,
            status=Payment.Status.SUCCESS,
        ).exists():
            raise ValidationError(
                {"hold_reference": "This ticket hold has already been paid."}
            )

        payment = Payment.objects.create(
            hold=hold,
            amount_subunit=amount_subunit,
            currency="NGN",
            status=Payment.Status.INITIALIZED,
        )

    # Make the external API request outside the database transaction.
    payload = {
        "email": attendee.email,
        "amount": payment.amount_subunit,
        "currency": payment.currency,
        "reference": payment.reference,
        "metadata": {
            "hold_reference": str(hold.reference),
            "payment_reference": payment.reference,
            "attendee_id": attendee.pk,
        },
    }

    headers = {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        response = requests.post(
            f"{settings.PAYSTACK_BASE_URL}/transaction/initialize",
            json=payload,
            headers=headers,
            timeout=(5, 20),
        )
        response.raise_for_status()
        result = response.json()

    except (requests.RequestException, ValueError) as exc:
        payment.status = Payment.Status.FAILED
        payment.save(update_fields=["status", "updated_at"])
        raise PaystackUnavailable() from exc

    if not result.get("status") or not result.get("data"):
        payment.status = Payment.Status.FAILED
        payment.provider_response = result
        payment.save(
            update_fields=["status", "provider_response", "updated_at"]
        )
        raise PaystackUnavailable(
            "Paystack could not initialize this transaction."
        )

    data = result["data"]
    authorization_url = data.get("authorization_url")
    access_code = data.get("access_code")

    if not authorization_url or not access_code:
        payment.status = Payment.Status.FAILED
        payment.provider_response = result
        payment.save(
            update_fields=["status", "provider_response", "updated_at"]
        )
        raise PaystackUnavailable(
            "Paystack returned an incomplete transaction response."
        )

    payment.authorization_url = authorization_url
    payment.access_code = access_code
    payment.status = Payment.Status.PENDING
    payment.provider_response = {
        "message": result.get("message"),
    }
    payment.save(
        update_fields=[
            "authorization_url",
            "access_code",
            "status",
            "provider_response",
            "updated_at",
        ]
    )

    return payment