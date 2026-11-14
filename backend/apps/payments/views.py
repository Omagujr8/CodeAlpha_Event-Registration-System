from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.payments.serializers import PaymentInitializeSerializer
from apps.payments.services import initialize_paystack_payment


class PaymentInitializeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = PaymentInitializeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        payment = initialize_paystack_payment(
            hold_reference=serializer.validated_data["hold_reference"],
            attendee=request.user,
        )

        return Response(
            {
                "message": "Payment initialized successfully.",
                "payment_reference": payment.reference,
                "amount_subunit": payment.amount_subunit,
                "currency": payment.currency,
                "authorization_url": payment.authorization_url,
            },
            status=status.HTTP_201_CREATED,
        )

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.payments.refunds import issue_paystack_refund


class PaystackRefundView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def post(self, request, payment_reference):
        attempt = issue_paystack_refund(
            payment_reference=payment_reference,
            requested_by=request.user,
        )
        response_status = (
            status.HTTP_200_OK
            if attempt.status == attempt.Status.PROCESSED
            else status.HTTP_202_ACCEPTED
        )
        return Response(
            {
                "payment_reference": attempt.payment.reference,
                "refund_status": attempt.status,
                "amount_subunit": attempt.amount_subunit,
                "provider_refund_id": attempt.provider_refund_id or None,
                "processed_at": attempt.processed_at,
            },
            status=response_status,
        )
