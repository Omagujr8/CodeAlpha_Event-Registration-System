import requests

from django.conf import settings
from rest_framework.exceptions import APIException, ValidationError


class PaymentVerificationUnavailable(APIException):
    status_code = 503
    default_detail = "Payment verification is temporarily unavailable."
    default_code = "payment_verification_unavailable"


def verify_paystack_transaction(payment):
    """
    Verify a transaction directly with Paystack.
    Never trust the webhook payload as proof of payment.
    """

    if not settings.PAYSTACK_SECRET_KEY:
        raise PaymentVerificationUnavailable(
            "Paystack is not configured."
        )

    url = (
        f"{settings.PAYSTACK_BASE_URL}"
        f"/transaction/verify/{payment.reference}"
    )

    headers = {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Accept": "application/json",
    }

    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=(5, 20),
        )
        response.raise_for_status()
        result = response.json()

    except (requests.RequestException, ValueError) as exc:
        raise PaymentVerificationUnavailable() from exc

    if (
        not result.get("status")
        or not isinstance(result.get("data"), dict)
    ):
        raise PaymentVerificationUnavailable(
            "Paystack returned an invalid verification response."
        )

    data = result["data"]

    if data.get("reference") != payment.reference:
        raise ValidationError("Payment reference does not match.")

    if data.get("status") != "success":
        return None

    if data.get("amount") != payment.amount_subunit:
        raise ValidationError("Verified payment amount does not match.")

    if data.get("currency") != payment.currency:
        raise ValidationError("Verified payment currency does not match.")

    transaction_id = data.get("id")

    if transaction_id is None or not str(transaction_id).strip():
        raise PaymentVerificationUnavailable(
            "Paystack did not provide a transaction ID."
        )

    return data