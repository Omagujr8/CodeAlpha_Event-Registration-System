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
    Reconcile an unresolved payment against Paystack.

    Both INITIALIZED transactions (where initialization response was uncertain)
    and PENDING transactions (where a webhook may have been missed) are checked.
    """
    try:
        payment = Payment.objects.get(reference=payment_reference)
    except Payment.DoesNotExist as exc:
        raise Payment.DoesNotExist(
            f"No payment exists with reference {payment_reference}."
        ) from exc

    unresolved_statuses = {
        Payment.Status.INITIALIZED,
        Payment.Status.PENDING,
    }
    if payment.status not in unresolved_statuses:
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
    if data.get("reference") != payment.reference:
        raise ReconciliationUnavailable(
            "The verified transaction reference does not match."
        )

    try:
        verified_amount = int(data.get("amount"))
    except (TypeError, ValueError) as exc:
        raise ReconciliationUnavailable(
            "Paystack returned an invalid transaction amount."
        ) from exc

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
        with transaction.atomic():
            locked_payment = (
                Payment.objects.select_for_update()
                .get(reference=payment.reference)
            )
            if locked_payment.status in unresolved_statuses:
                locked_payment.status = (
                    Payment.Status.FAILED
                    if provider_status == "failed"
                    else Payment.Status.ABANDONED
                )
                locked_payment.provider_response = {
                    "reconciliation": {
                        "provider_status": provider_status,
                        "checked_at": timezone.now().isoformat(),
                        "retryable": True,
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

    return {
        "reference": payment.reference,
        "result": "manual_review",
        "detail": (
            "Unrecognized Paystack transaction status: "
            f"{provider_status!r}."
        ),
    }
