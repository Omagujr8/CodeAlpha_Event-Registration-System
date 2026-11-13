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


class PaymentInitializationInProgress(APIException):
    status_code = 409
    default_detail = (
        "A payment attempt already exists and requires reconciliation. "
        "Please do not start another payment."
    )
    default_code = "payment_initialization_in_progress"


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

    # Lock the hold so concurrent requests cannot create
    # multiple payment attempts for the same hold.
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

        # Inspect previous payment attempts before creating another.
        previous_payments = Payment.objects.filter(
            hold=hold,
        ).order_by("-created_at")

        if previous_payments.filter(
            status=Payment.Status.SUCCESS,
        ).exists():
            raise ValidationError(
                {"hold_reference": "This ticket hold has already been paid."}
            )

        if previous_payments.filter(
            status=Payment.Status.REFUND_REQUIRED,
        ).exists():
            raise ValidationError(
                {
                    "hold_reference": (
                        "This hold has a payment requiring resolution."
                    )
                }
            )

        latest_payment = previous_payments.first()

        if latest_payment:
            if latest_payment.status == Payment.Status.PENDING:
                if latest_payment.authorization_url:
                    # Reuse the existing checkout session.
                    return latest_payment

                raise PaymentInitializationInProgress()

            if latest_payment.status == Payment.Status.INITIALIZED:
                raise PaymentInitializationInProgress()

            if latest_payment.status == Payment.Status.ABANDONED:
                reconciliation = (
                    latest_payment.provider_response.get("reconciliation") or {}
                )
                if reconciliation.get("retryable") is not True:
                    raise PaymentInitializationInProgress()

            if latest_payment.status == Payment.Status.FAILED:
                # Only retry when we have evidence that Paystack
                # explicitly rejected the initialization request.
                provider_response = latest_payment.provider_response or {}

                reconciliation = provider_response.get("reconciliation") or {}
                safely_retryable = (
                    provider_response.get("initialization_rejected") is True
                    or reconciliation.get("retryable") is True
                )
                if not safely_retryable:
                    raise PaymentInitializationInProgress()

        payment = Payment.objects.create(
            hold=hold,
            amount_subunit=amount_subunit,
            currency="NGN",
            status=Payment.Status.INITIALIZED,
        )

    # Do not keep a database transaction open during network requests.
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
        # IMPORTANT:
        # Do not mark this payment FAILED.
        # Paystack may have received the request even if our
        # application did not receive its response.
        #
        # Keep INITIALIZED so another request cannot create
        # a second transaction for the same hold.
        raise PaystackUnavailable(
            "The payment initialization outcome is uncertain. "
            "Please do not retry payment until this attempt is reconciled."
        ) from exc

    if not isinstance(result, dict):
        raise PaystackUnavailable(
            "Paystack returned an invalid initialization response."
        )

    if result.get("status") is False:
        # This is an explicit provider rejection, not a timeout.
        payment.status = Payment.Status.FAILED
        payment.provider_response = {
            "message": result.get("message"),
            "initialization_rejected": True,
        }

        payment.save(
            update_fields=[
                "status",
                "provider_response",
                "updated_at",
            ]
        )

        raise PaystackUnavailable(
            "Paystack rejected the payment initialization request."
        )

    if result.get("status") is not True:
        # An unclear response must be reconciled, not retried blindly.
        raise PaystackUnavailable(
            "Paystack returned an uncertain initialization response."
        )

    data = result.get("data")

    if not isinstance(data, dict):
        raise PaystackUnavailable(
            "Paystack returned an incomplete transaction response."
        )

    if data.get("reference") != payment.reference:
        # A mismatched response is uncertain; keep the payment INITIALIZED
        # so reconciliation can inspect the reference we generated.
        raise PaystackUnavailable(
            "Paystack returned a transaction with an unexpected reference."
        )

    authorization_url = data.get("authorization_url")
    access_code = data.get("access_code")

    if not authorization_url or not access_code:
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