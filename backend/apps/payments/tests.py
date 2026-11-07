from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock, patch

import requests

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone

from rest_framework import status
from rest_framework.test import APITestCase

from apps.events.models import Event, TicketTier
from apps.ticketing.models import TicketHold
from apps.payments.models import Payment


User = get_user_model()


@override_settings(
    PAYSTACK_SECRET_KEY="sk_test_example",
    PAYSTACK_BASE_URL="https://api.paystack.co",
)
class PaymentInitializationTests(APITestCase):

    def setUp(self):
        self.attendee = User.objects.create_user(
            username="attendee",
            email="attendee@example.com",
            password="TestPassword123!",
        )

        self.other_user = User.objects.create_user(
            username="other",
            email="other@example.com",
            password="TestPassword123!",
        )

        now = timezone.now()

        self.event = Event.objects.create(
            organizer=self.attendee,
            title="Backend Conference",
            slug="backend-conference",
            description="A technology conference.",
            venue="Minna",
            starts_at=now + timedelta(days=10),
            ends_at=now + timedelta(days=11),
            status=Event.Status.PUBLISHED,
        )

        self.ticket_tier = TicketTier.objects.create(
            event=self.event,
            name="Regular",
            price=Decimal("1500.00"),
            currency="NGN",
            total_quantity=100,
            sold_quantity=0,
            is_active=True,
        )

        self.hold = TicketHold.objects.create(
            attendee=self.attendee,
            ticket_tier=self.ticket_tier,
            quantity=2,
            status=TicketHold.Status.ACTIVE,
            expires_at=now + timedelta(minutes=10),
        )

        self.url = "/api/payments/initialize/"

        self.paystack_response = {
            "status": True,
            "message": "Authorization URL created",
            "data": {
                "authorization_url": (
                    "https://checkout.paystack.com/example"
                ),
                "access_code": "example_access_code",
                "reference": "example_reference",
            },
        }

    @patch("apps.payments.services.requests.post")
    def test_attendee_can_initialize_payment(self, mock_post):
        mock_response = Mock()
        mock_response.json.return_value = self.paystack_response
        mock_post.return_value = mock_response

        self.client.force_authenticate(user=self.attendee)

        response = self.client.post(
            self.url,
            {"hold_reference": str(self.hold.reference)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            response.data["amount_subunit"],
            300000,
        )
        self.assertEqual(response.data["currency"], "NGN")
        self.assertEqual(
            response.data["authorization_url"],
            "https://checkout.paystack.com/example",
        )

        payment = Payment.objects.get(hold=self.hold)

        self.assertEqual(payment.amount_subunit, 300000)
        self.assertEqual(payment.status, Payment.Status.PENDING)

        mock_post.assert_called_once()

    @patch("apps.payments.services.requests.post")
    def test_attendee_cannot_pay_for_another_users_hold(self, mock_post):
        self.client.force_authenticate(user=self.other_user)

        response = self.client.post(
            self.url,
            {"hold_reference": str(self.hold.reference)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Payment.objects.count(), 0)
        mock_post.assert_not_called()

    @patch("apps.payments.services.requests.post")
    def test_expired_hold_cannot_be_paid(self, mock_post):
        self.hold.expires_at = timezone.now() - timedelta(minutes=1)
        self.hold.save(update_fields=["expires_at"])

        self.client.force_authenticate(user=self.attendee)

        response = self.client.post(
            self.url,
            {"hold_reference": str(self.hold.reference)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Payment.objects.count(), 0)
        mock_post.assert_not_called()

    @patch("apps.payments.services.requests.post")
    def test_paystack_connection_failure_marks_payment_failed(
        self,
        mock_post,
    ):
        mock_post.side_effect = requests.Timeout()

        self.client.force_authenticate(user=self.attendee)

        response = self.client.post(
            self.url,
            {"hold_reference": str(self.hold.reference)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)

        payment = Payment.objects.get(hold=self.hold)
        self.assertEqual(payment.status, Payment.Status.FAILED)

    @patch("apps.payments.services.requests.post")
    def test_client_cannot_supply_its_own_payment_amount(self, mock_post):
        mock_response = Mock()
        mock_response.json.return_value = self.paystack_response
        mock_post.return_value = mock_response

        self.client.force_authenticate(user=self.attendee)

        response = self.client.post(
            self.url,
            {
                "hold_reference": str(self.hold.reference),
                "amount": 1,
                "currency": "USD",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        payment = Payment.objects.get(hold=self.hold)
        self.assertEqual(payment.amount_subunit, 300000)
        self.assertEqual(payment.currency, "NGN")