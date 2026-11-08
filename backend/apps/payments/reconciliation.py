import requests

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException

from apps.payments.confirmation import confirm_successful_payment
from apps.payments.models import Payment


class ReconciliationUnavailable(APIException):
    status_code = 503
    default_detail = "Paystack payment reconciliation is temporarily unavailable."
    default_code = "reconciliation_unavailable"


def reconcile_payment(*, payment_reference):
    """
    Reconcile an unresolved INITIALIZED payment against Paystack.

    This function never creates a new payment or changes the payment reference.
    """
    try:
        payment = Payment.objects.get(reference=payment_reference)
    except Payment.DoesNotExist:
        raise Payment.DoesNotExist(
            f"No payment exists with reference {payment_reference}."
        )

    if payment.status != Payment.Status.INITIALIZED:
        return {
            "reference": payment.reference,
            "result": "skipped",
            "detail": f"Payment is already {payment.status}.",
        }

    if not settings.PAYSTACK_SECRET_KEY:
        raise ReconciliationUnavailable("Paystack is not configured.")

    url = (
        f"{settings.PAYSTACK_BASE_URL}/transaction/verify/"
        f"{payment.reference}"
    )
    headers = {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Accept": "application/json",
    }

    try:
        response = requests.get(url, headers=headers, timeout=(5, 20))
        response.raise_for_status()
        result = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise ReconciliationUnavailable() from exc

    if (
        not isinstance(result, dict)
        or result.get("status") is not True
        or not isinstance(result.get("data"), dict)
    ):
        raise ReconciliationUnavailable(
            "Paystack returned an invalid verification response."
        )

    data = result["data"]

    # Never reconcile a transaction belonging to another reference.
    if data.get("reference") != payment.reference:
        raise ReconciliationUnavailable(
            "The verified transaction reference does not match."
        )

    # Confirm that the provider is reporting the expected amount and currency.
    try:
        verified_amount = int(data.get("amount"))
    except (TypeError, ValueError):
        raise ReconciliationUnavailable(
            "Paystack returned an invalid transaction amount."
        )

    if verified_amount != payment.amount_subunit:
        raise ReconciliationUnavailable(
            "The verified transaction amount does not match."
        )

    if data.get("currency") != payment.currency:
        raise ReconciliationUnavailable(
            "The verified transaction currency does not match."
        )

    provider_status = data.get("status")

    if provider_status == "success":
        transaction_id = data.get("id")
        if transaction_id is None or not str(transaction_id).strip():
            raise ReconciliationUnavailable(
                "Paystack did not provide a transaction ID."
            )

        # The existing confirmation service handles locking, inventory,
        # registration creation, and duplicate-event protection.
        confirm_successful_payment(
            payment_reference=payment.reference,
            verified_data=data,
        )

        payment.refresh_from_db()

        return {
            "reference": payment.reference,
            "result": payment.status,
            "detail": "Successful transaction was processed.",
        }

    if provider_status == "pending":
        return {
            "reference": payment.reference,
            "result": "pending",
            "detail": "Paystack still reports this transaction as pending.",
        }

    if provider_status in {"failed", "abandoned"}:
        # Lock again because a webhook could have confirmed the payment
        # while the verification request was in progress.
        with transaction.atomic():
            locked_payment = (
                Payment.objects.select_for_update()
                .get(reference=payment.reference)
            )

            if locked_payment.status == Payment.Status.INITIALIZED:
                locked_payment.status = Payment.Status.FAILED
                locked_payment.provider_response = {
                    "reconciliation": {
                        "provider_status": provider_status,
                        "checked_at": timezone.now().isoformat(),
                    }
                }
                locked_payment.save(
                    update_fields=[
                        "status",
                        "provider_response",
                        "updated_at",
                    ]
                )

        payment.refresh_from_db()

        return {
            "reference": payment.reference,
            "result": payment.status,
            "detail": "Paystack reported a failed or abandoned transaction.",
        }

    # Unknown states, including reversed, must not be treated as a safe
    # failure. Leave the payment unresolved for investigation.
    return {
        "reference": payment.reference,
        "result": "manual_review",
        "detail": f"Unrecognized Paystack transaction status: {provider_status!r}.",
    }