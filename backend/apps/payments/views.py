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