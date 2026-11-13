from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.events.models import Event, TicketTier
from apps.payments.models import Payment
from apps.payments.reconciliation import reconcile_payment
from apps.registrations.models import Registration
from apps.ticketing.models import TicketHold


User = get_user_model()


@override_settings(
    PAYSTACK_SECRET_KEY="sk_test_example",
    PAYSTACK_BASE_URL="https://api.paystack.co",
)
class PaymentReconciliationTests(TestCase):
    def setUp(self):
        self.attendee = User.objects.create_user(
            username="reconcile_attendee",
            email="reconcile@example.com",
            password="TestPassword123!",
        )
        now = timezone.now()
        self.event = Event.objects.create(
            organizer=self.attendee,
            title="Reconciliation Conference",
            slug="reconciliation-conference",
            description="Payment reconciliation tests.",
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

    def provider_response(self, provider_status):
        return {
            "status": True,
            "data": {
                "id": 987654321,
                "reference": self.payment.reference,
                "status": provider_status,
                "amount": 300000,
                "currency": "NGN",
            },
        }

    @patch("apps.payments.reconciliation.requests.get")
    def test_pending_payment_is_reconciled_after_missed_webhook(
        self, mock_get
    ):
        response = Mock()
        response.json.return_value = self.provider_response("success")
        mock_get.return_value = response

        result = reconcile_payment(payment_reference=self.payment.reference)

        self.payment.refresh_from_db()
        self.hold.refresh_from_db()
        self.ticket_tier.refresh_from_db()

        self.assertEqual(result["result"], Payment.Status.SUCCESS)
        self.assertEqual(self.payment.status, Payment.Status.SUCCESS)
        self.assertEqual(self.hold.status, TicketHold.Status.CONVERTED)
        self.assertEqual(self.ticket_tier.sold_quantity, 2)
        self.assertEqual(
            Registration.objects.filter(ticket_hold=self.hold).count(),
            1,
        )

    @patch("apps.payments.reconciliation.requests.get")
    def test_pending_provider_status_does_not_change_payment(
        self, mock_get
    ):
        response = Mock()
        response.json.return_value = self.provider_response("pending")
        mock_get.return_value = response

        result = reconcile_payment(payment_reference=self.payment.reference)

        self.payment.refresh_from_db()
        self.assertEqual(result["result"], "pending")
        self.assertEqual(self.payment.status, Payment.Status.PENDING)

    @patch("apps.payments.reconciliation.requests.get")
    def test_verified_failure_is_marked_retryable(self, mock_get):
        response = Mock()
        response.json.return_value = self.provider_response("failed")
        mock_get.return_value = response

        result = reconcile_payment(payment_reference=self.payment.reference)

        self.payment.refresh_from_db()
        self.assertEqual(result["result"], Payment.Status.FAILED)
        self.assertEqual(self.payment.status, Payment.Status.FAILED)
        self.assertTrue(
            self.payment.provider_response["reconciliation"]["retryable"]
        )

    @patch("apps.payments.reconciliation.requests.get")
    def test_abandoned_payment_is_marked_abandoned_and_retryable(
        self, mock_get
    ):
        response = Mock()
        response.json.return_value = self.provider_response("abandoned")
        mock_get.return_value = response

        result = reconcile_payment(payment_reference=self.payment.reference)

        self.payment.refresh_from_db()
        self.assertEqual(result["result"], Payment.Status.ABANDONED)
        self.assertEqual(self.payment.status, Payment.Status.ABANDONED)
        self.assertTrue(
            self.payment.provider_response["reconciliation"]["retryable"]
        )

    @patch("apps.payments.reconciliation.requests.get")
    def test_reference_mismatch_is_not_reconciled(self, mock_get):
        data = self.provider_response("success")
        data["data"]["reference"] = "another-reference"
        response = Mock()
        response.json.return_value = data
        mock_get.return_value = response

        with self.assertRaises(Exception):
            reconcile_payment(payment_reference=self.payment.reference)

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.PENDING)
        self.assertEqual(Registration.objects.count(), 0)
