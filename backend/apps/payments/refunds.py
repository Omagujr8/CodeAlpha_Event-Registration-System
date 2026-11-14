import requests

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, ValidationError

from apps.payments.models import Payment, RefundAttempt


class RefundServiceUnavailable(APIException):
    status_code = 503
    default_detail = "Paystack refund service is temporarily unavailable."
    default_code = "refund_service_unavailable"


def issue_paystack_refund(*, payment_reference, requested_by):
    if not settings.PAYSTACK_SECRET_KEY:
        raise RefundServiceUnavailable("Paystack is not configured.")

    with transaction.atomic():
        try:
            payment = Payment.objects.select_for_update().get(reference=payment_reference)
        except Payment.DoesNotExist:
            raise ValidationError({"payment_reference": "Payment does not exist."})

        if payment.status == Payment.Status.REFUNDED:
            try:
                return payment.refund
            except RefundAttempt.DoesNotExist:
                raise ValidationError("Payment is marked refunded without a refund record.")

        if payment.status != Payment.Status.REFUND_REQUIRED:
            raise ValidationError("Only payments marked REFUND_REQUIRED can be refunded.")

        if not payment.provider_transaction_id:
            raise ValidationError("A verified Paystack transaction ID is required.")

        attempt, created = RefundAttempt.objects.get_or_create(
            payment=payment,
            defaults={
                "amount_subunit": payment.amount_subunit,
                "requested_by": requested_by,
                "status": RefundAttempt.Status.PENDING,
            },
        )
        if not created:
            if attempt.status == RefundAttempt.Status.PROCESSED:
                return attempt
            if attempt.status == RefundAttempt.Status.PENDING:
                # The previous request may have reached Paystack. Do not
                # submit a duplicate refund while its outcome is uncertain.
                return attempt
            attempt.status = RefundAttempt.Status.PENDING
            attempt.provider_response = {}
            attempt.requested_by = requested_by
            attempt.save(update_fields=["status", "provider_response", "requested_by", "updated_at"])

    payload = {
        "transaction": payment.provider_transaction_id,
        "amount": attempt.amount_subunit,
        "currency": payment.currency,
        "customer_note": "Refund for an unfulfilled event ticket purchase.",
        "merchant_note": f"Event registration payment {payment.reference}",
    }
    headers = {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        response = requests.post(
            f"{settings.PAYSTACK_BASE_URL}/refund",
            json=payload,
            headers=headers,
            timeout=(5, 20),
        )
        response.raise_for_status()
        result = response.json()
    except (requests.RequestException, ValueError) as exc:
        # Keep PENDING: a timeout does not prove Paystack did not create
        # the refund. An operator must reconcile before retrying.
        attempt.provider_response = {"outcome": "unknown", "error": str(exc)[:1000]}
        attempt.save(update_fields=["provider_response", "updated_at"])
        raise RefundServiceUnavailable(
            "Refund outcome is uncertain. Check the Paystack dashboard before retrying."
        ) from exc

    if not isinstance(result, dict) or result.get("status") is not True:
        attempt.status = RefundAttempt.Status.FAILED
        attempt.provider_response = result if isinstance(result, dict) else {"response": "invalid"}
        attempt.save(update_fields=["status", "provider_response", "updated_at"])
        raise RefundServiceUnavailable("Paystack rejected the refund request.")

    data = result.get("data")
    if not isinstance(data, dict):
        attempt.provider_response = {"outcome": "unknown", "message": "Invalid refund response"}
        attempt.save(update_fields=["provider_response", "updated_at"])
        raise RefundServiceUnavailable("Paystack returned an incomplete refund response.")

    provider_status = str(data.get("status", "")).lower()
    attempt.provider_refund_id = str(data.get("id") or "")
    attempt.provider_response = data

    if provider_status in {"processed", "success"}:
        attempt.status = RefundAttempt.Status.PROCESSED
        attempt.processed_at = timezone.now()
        attempt.save(update_fields=["status", "provider_refund_id", "provider_response", "processed_at", "updated_at"])
        Payment.objects.filter(pk=payment.pk, status=Payment.Status.REFUND_REQUIRED).update(
            status=Payment.Status.REFUNDED,
            updated_at=timezone.now(),
        )
    elif provider_status in {"pending", "processing"}:
        attempt.status = RefundAttempt.Status.PENDING
        attempt.save(update_fields=["status", "provider_refund_id", "provider_response", "updated_at"])
    else:
        attempt.status = RefundAttempt.Status.FAILED
        attempt.save(update_fields=["status", "provider_refund_id", "provider_response", "updated_at"])

    return attempt
