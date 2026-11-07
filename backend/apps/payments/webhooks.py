import hashlib
import hmac

from django.conf import settings
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.payments.models import Payment
from apps.payments.confirmation import confirm_successful_payment
from apps.payments.verification import verify_paystack_transaction


@method_decorator(csrf_exempt, name="dispatch")
class PaystackWebhookView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        signature = (
            request.headers.get("x-paystack-signature")
            or request.headers.get("Paystack-Signature")
        )

        if not signature or not settings.PAYSTACK_SECRET_KEY:
            return Response(
                {"detail": "Invalid webhook signature."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        expected_signature = hmac.new(
            settings.PAYSTACK_SECRET_KEY.encode("utf-8"),
            request.body,
            hashlib.sha512,
        ).hexdigest()

        if not hmac.compare_digest(signature, expected_signature):
            return Response(
                {"detail": "Invalid webhook signature."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        event = request.data

        if event.get("event") != "charge.success":
            return Response({"received": True}, status=status.HTTP_200_OK)

        data = event.get("data") or {}
        reference = data.get("reference")

        if not reference:
            return Response(
                {"received": True},
                status=status.HTTP_200_OK,
            )

        payment = Payment.objects.filter(reference=reference).first()

        # Acknowledge events that do not belong to our payment records.
        if payment is None:
            return Response(
                {"received": True},
                status=status.HTTP_200_OK,
            )

        verified_data = verify_paystack_transaction(payment)

        # A valid notification is not necessarily a successful payment.
        if verified_data is None:
            return Response(
                {"received": True},
                status=status.HTTP_200_OK,
            )

        confirm_successful_payment(
            payment_reference=payment.reference,
            verified_data=verified_data,
        )

        return Response(
            {"received": True},
            status=status.HTTP_200_OK,
        )