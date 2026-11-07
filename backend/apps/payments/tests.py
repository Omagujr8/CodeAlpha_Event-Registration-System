from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock, patch

import requests
import hashlib
import hmac
import json

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone

from rest_framework import status
from rest_framework.test import APITestCase

from apps.events.models import Event, TicketTier
from apps.ticketing.models import TicketHold
from apps.payments.models import Payment
from apps.registrations.models import Registration


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

@override_settings(
    PAYSTACK_SECRET_KEY="sk_test_example",
    PAYSTACK_BASE_URL="https://api.paystack.co",
)
class PaystackWebhookTests(APITestCase):

    def setUp(self):
        self.attendee = User.objects.create_user(
            username="webhook_attendee",
            email="webhook@example.com",
            password="TestPassword123!",
        )

        now = timezone.now()

        self.event = Event.objects.create(
            organizer=self.attendee,
            title="Webhook Conference",
            slug="webhook-conference",
            description="Testing payment webhooks.",
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

        self.payment = Payment.objects.create(
            hold=self.hold,
            amount_subunit=300000,
            currency="NGN",
            status=Payment.Status.PENDING,
        )

        self.url = "/api/payments/webhook/paystack/"

        self.webhook_payload = {
            "event": "charge.success",
            "data": {
                "reference": self.payment.reference,
                "status": "success",
                "amount": 300000,
                "currency": "NGN",
            },
        }

        self.verified_data = {
            "id": 123456789,
            "reference": self.payment.reference,
            "status": "success",
            "amount": 300000,
            "currency": "NGN",
        }

    def send_webhook(self, payload=None, signature=None):
        """
        Send a webhook with a signature calculated from its exact raw body.
        """
        payload = payload or self.webhook_payload

        raw_body = json.dumps(
            payload,
            separators=(",", ":"),
        ).encode("utf-8")

        if signature is None:
            signature = hmac.new(
                b"sk_test_example",
                raw_body,
                hashlib.sha512,
            ).hexdigest()

        return self.client.generic(
            "POST",
            self.url,
            data=raw_body,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=signature,
        )

    @patch("apps.payments.webhooks.verify_paystack_transaction")
    def test_valid_webhook_confirms_payment_and_registration(
        self,
        mock_verify,
    ):
        mock_verify.return_value = self.verified_data

        response = self.send_webhook()

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.payment.refresh_from_db()
        self.hold.refresh_from_db()
        self.ticket_tier.refresh_from_db()

        self.assertEqual(
            self.payment.status,
            Payment.Status.SUCCESS,
        )

        self.assertEqual(
            self.hold.status,
            TicketHold.Status.CONVERTED,
        )

        self.assertEqual(self.ticket_tier.sold_quantity, 2)

        self.assertEqual(
            Registration.objects.filter(
                ticket_hold=self.hold,
            ).count(),
            1,
        )

        mock_verify.assert_called_once()

    @patch("apps.payments.webhooks.verify_paystack_transaction")
    def test_duplicate_webhook_does_not_duplicate_registration(
        self,
        mock_verify,
    ):
        mock_verify.return_value = self.verified_data

        first_response = self.send_webhook()
        second_response = self.send_webhook()

        self.assertEqual(
            first_response.status_code,
            status.HTTP_200_OK,
        )

        self.assertEqual(
            second_response.status_code,
            status.HTTP_200_OK,
        )

        self.payment.refresh_from_db()
        self.ticket_tier.refresh_from_db()

        self.assertEqual(
            self.payment.status,
            Payment.Status.SUCCESS,
        )

        self.assertEqual(self.ticket_tier.sold_quantity, 2)

        self.assertEqual(
            Registration.objects.filter(
                ticket_hold=self.hold,
            ).count(),
            1,
        )

        self.assertEqual(mock_verify.call_count, 2)

    @patch("apps.payments.webhooks.verify_paystack_transaction")
    def test_invalid_signature_is_rejected(self, mock_verify):
        response = self.send_webhook(
            signature="invalid_signature",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

        self.assertEqual(Payment.Status.PENDING, self.payment.status)

        mock_verify.assert_not_called()

    @patch("apps.payments.webhooks.verify_paystack_transaction")
    def test_non_success_event_does_not_confirm_payment(
        self,
        mock_verify,
    ):
        payload = {
            "event": "charge.failed",
            "data": {
                "reference": self.payment.reference,
            },
        }

        response = self.send_webhook(payload=payload)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.payment.refresh_from_db()
        self.ticket_tier.refresh_from_db()

        self.assertEqual(
            self.payment.status,
            Payment.Status.PENDING,
        )

        self.assertEqual(self.ticket_tier.sold_quantity, 0)
        self.assertEqual(Registration.objects.count(), 0)

        mock_verify.assert_not_called()

    @patch("apps.payments.webhooks.verify_paystack_transaction")
    def test_verification_failure_returns_service_unavailable(
        self,
        mock_verify,
    ):
        from apps.payments.verification import (
            PaymentVerificationUnavailable,
        )

        mock_verify.side_effect = PaymentVerificationUnavailable()

        response = self.send_webhook()

        self.assertEqual(
            response.status_code,
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )

        self.payment.refresh_from_db()

        self.assertEqual(
            self.payment.status,
            Payment.Status.PENDING,
        )

        self.assertEqual(Registration.objects.count(), 0)

    @patch("apps.payments.webhooks.verify_paystack_transaction")
    def test_incorrect_verified_amount_is_rejected(
        self,
        mock_verify,
    ):
        incorrect_data = {
            **self.verified_data,
            "amount": 100,
        }

        mock_verify.return_value = incorrect_data

        response = self.send_webhook()

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.payment.refresh_from_db()
        self.ticket_tier.refresh_from_db()

        self.assertEqual(
            self.payment.status,
            Payment.Status.PENDING,
        )

        self.assertEqual(self.ticket_tier.sold_quantity, 0)
        self.assertEqual(Registration.objects.count(), 0)