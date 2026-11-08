from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock, patch

import requests
import hashlib
import hmac
import json
from io import StringIO

from django.core.management import call_command

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone

from rest_framework import status
from rest_framework.test import APITestCase

from apps.events.models import Event, TicketTier
from apps.ticketing.models import TicketHold
from apps.payments.models import Payment
from apps.registrations.models import Registration
from apps.payments.reconciliation import (
    ReconciliationUnavailable,
    reconcile_payment,
)


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
    def test_paystack_timeout_keeps_payment_initialized(
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

        self.assertEqual(
            response.status_code,
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )

        payment = Payment.objects.get(hold=self.hold)

        self.assertEqual(
            payment.status,
            Payment.Status.INITIALIZED,
        )

        self.assertEqual(Payment.objects.count(), 1)

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

    @patch("apps.payments.services.requests.post")
    def test_repeated_initialization_reuses_existing_pending_payment(
        self,
        mock_post,
    ):
        mock_response = Mock()
        mock_response.json.return_value = self.paystack_response
        mock_post.return_value = mock_response

        self.client.force_authenticate(user=self.attendee)

        first_response = self.client.post(
            self.url,
            {"hold_reference": str(self.hold.reference)},
            format="json",
        )

        second_response = self.client.post(
            self.url,
            {"hold_reference": str(self.hold.reference)},
            format="json",
        )

        self.assertEqual(
            first_response.status_code,
            status.HTTP_201_CREATED,
        )
        self.assertEqual(
            second_response.status_code,
            status.HTTP_201_CREATED,
        )

        self.assertEqual(
            first_response.data["payment_reference"],
            second_response.data["payment_reference"],
        )

        self.assertEqual(Payment.objects.filter(hold=self.hold).count(), 1)
        mock_post.assert_called_once()

    @patch("apps.payments.services.requests.post")
    def test_existing_initializing_payment_blocks_new_attempt(
        self,
        mock_post,
    ):
        Payment.objects.create(
            hold=self.hold,
            amount_subunit=300000,
            currency="NGN",
            status=Payment.Status.INITIALIZED,
        )

        self.client.force_authenticate(user=self.attendee)

        response = self.client.post(
            self.url,
            {"hold_reference": str(self.hold.reference)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(Payment.objects.filter(hold=self.hold).count(), 1)
        mock_post.assert_not_called()

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

    @patch("apps.payments.webhooks.verify_paystack_transaction")
    def test_expired_hold_marks_successful_payment_refund_required(
        self,
        mock_verify,
    ):
        mock_verify.return_value = self.verified_data

        self.hold.expires_at = timezone.now() - timedelta(minutes=1)
        self.hold.save(update_fields=["expires_at"])

        response = self.send_webhook()

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.payment.refresh_from_db()
        self.hold.refresh_from_db()
        self.ticket_tier.refresh_from_db()

        self.assertEqual(
            self.payment.status,
            Payment.Status.REFUND_REQUIRED,
        )
        self.assertIsNotNone(self.payment.paid_at)
        self.assertEqual(
            self.payment.provider_response["resolution_reason"],
            "Ticket hold expired before fulfillment.",
        )
        self.assertEqual(
            self.hold.status,
            TicketHold.Status.EXPIRED,
        )
        self.assertEqual(self.ticket_tier.sold_quantity, 0)
        self.assertEqual(Registration.objects.count(), 0)

    @patch("apps.payments.webhooks.verify_paystack_transaction")
    def test_unavailable_inventory_marks_payment_refund_required(
        self,
        mock_verify,
    ):
        mock_verify.return_value = self.verified_data

        self.ticket_tier.sold_quantity = 99
        self.ticket_tier.save(update_fields=["sold_quantity"])

        response = self.send_webhook()

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.payment.refresh_from_db()
        self.ticket_tier.refresh_from_db()

        self.assertEqual(
            self.payment.status,
            Payment.Status.REFUND_REQUIRED,
        )
        self.assertIsNotNone(self.payment.paid_at)
        self.assertEqual(
            self.payment.provider_response["resolution_reason"],
            "Insufficient ticket inventory for fulfillment.",
        )
        self.assertEqual(self.ticket_tier.sold_quantity, 99)
        self.assertEqual(Registration.objects.count(), 0)

    @patch("apps.payments.webhooks.verify_paystack_transaction")
    def test_duplicate_webhook_does_not_process_refund_required_payment_twice(
        self,
        mock_verify,
    ):
        mock_verify.return_value = self.verified_data

        self.hold.expires_at = timezone.now() - timedelta(minutes=1)
        self.hold.save(update_fields=["expires_at"])

        first_response = self.send_webhook()
        second_response = self.send_webhook()

        self.assertEqual(first_response.status_code, status.HTTP_200_OK)
        self.assertEqual(second_response.status_code, status.HTTP_200_OK)

        self.payment.refresh_from_db()

        self.assertEqual(
            self.payment.status,
            Payment.Status.REFUND_REQUIRED,
        )
        self.assertEqual(
            Registration.objects.filter(ticket_hold=self.hold).count(),
            0,
        )
        self.assertEqual(
            self.payment.provider_response["resolution_reason"],
            "Ticket hold expired before fulfillment.",
        )

@override_settings(
    PAYSTACK_SECRET_KEY="sk_test_example",
    PAYSTACK_BASE_URL="https://api.paystack.co",
)
class PaymentReconciliationTests(APITestCase):

    def setUp(self):
        self.attendee = User.objects.create_user(
            username="reconciliation_attendee",
            email="reconciliation@example.com",
            password="TestPassword123!",
        )

        now = timezone.now()

        self.event = Event.objects.create(
            organizer=self.attendee,
            title="Reconciliation Conference",
            slug="reconciliation-conference",
            description="Testing payment reconciliation.",
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
            status=Payment.Status.INITIALIZED,
        )

        self.verified_data = {
            "id": 987654321,
            "reference": self.payment.reference,
            "status": "success",
            "amount": 300000,
            "currency": "NGN",
        }

    def make_paystack_response(self, data=None):
        mock_response = Mock()
        mock_response.json.return_value = {
            "status": True,
            "message": "Verification successful",
            "data": data or self.verified_data,
        }
        return mock_response

    @patch("apps.payments.reconciliation.requests.get")
    def test_successful_reconciliation_confirms_payment(self, mock_get):
        mock_get.return_value = self.make_paystack_response()

        result = reconcile_payment(
            payment_reference=self.payment.reference,
        )

        self.payment.refresh_from_db()
        self.hold.refresh_from_db()
        self.ticket_tier.refresh_from_db()

        self.assertEqual(result["result"], Payment.Status.SUCCESS)
        self.assertEqual(self.payment.status, Payment.Status.SUCCESS)
        self.assertEqual(self.hold.status, TicketHold.Status.CONVERTED)
        self.assertEqual(self.ticket_tier.sold_quantity, 2)

        self.assertTrue(
            Registration.objects.filter(
                ticket_hold=self.hold,
                status=Registration.Status.CONFIRMED,
            ).exists()
        )

        mock_get.assert_called_once()

    @patch("apps.payments.reconciliation.requests.get")
    def test_pending_transaction_remains_initialized(self, mock_get):
        pending_data = {
            **self.verified_data,
            "status": "pending",
        }
        mock_get.return_value = self.make_paystack_response(pending_data)

        result = reconcile_payment(
            payment_reference=self.payment.reference,
        )

        self.payment.refresh_from_db()

        self.assertEqual(result["result"], "pending")
        self.assertEqual(
            self.payment.status,
            Payment.Status.INITIALIZED,
        )
        self.assertEqual(Registration.objects.count(), 0)

    @patch("apps.payments.reconciliation.requests.get")
    def test_failed_transaction_marks_payment_failed(self, mock_get):
        failed_data = {
            **self.verified_data,
            "status": "failed",
        }
        mock_get.return_value = self.make_paystack_response(failed_data)

        result = reconcile_payment(
            payment_reference=self.payment.reference,
        )

        self.payment.refresh_from_db()

        self.assertEqual(result["result"], Payment.Status.FAILED)
        self.assertEqual(self.payment.status, Payment.Status.FAILED)
        self.assertEqual(
            self.payment.provider_response["reconciliation"]["provider_status"],
            "failed",
        )
        self.assertEqual(Registration.objects.count(), 0)

    @patch("apps.payments.reconciliation.requests.get")
    def test_abandoned_transaction_marks_payment_failed(self, mock_get):
        abandoned_data = {
            **self.verified_data,
            "status": "abandoned",
        }
        mock_get.return_value = self.make_paystack_response(abandoned_data)

        result = reconcile_payment(
            payment_reference=self.payment.reference,
        )

        self.payment.refresh_from_db()

        self.assertEqual(result["result"], Payment.Status.FAILED)
        self.assertEqual(self.payment.status, Payment.Status.FAILED)

    @patch("apps.payments.reconciliation.requests.get")
    def test_network_timeout_leaves_payment_initialized(self, mock_get):
        mock_get.side_effect = requests.Timeout()

        with self.assertRaises(ReconciliationUnavailable):
            reconcile_payment(
                payment_reference=self.payment.reference,
            )

        self.payment.refresh_from_db()

        self.assertEqual(
            self.payment.status,
            Payment.Status.INITIALIZED,
        )
        self.assertEqual(Registration.objects.count(), 0)

    @patch("apps.payments.reconciliation.requests.get")
    def test_reference_mismatch_does_not_change_payment(self, mock_get):
        incorrect_data = {
            **self.verified_data,
            "reference": "some-other-payment-reference",
        }
        mock_get.return_value = self.make_paystack_response(incorrect_data)

        with self.assertRaises(ReconciliationUnavailable):
            reconcile_payment(
                payment_reference=self.payment.reference,
            )

        self.payment.refresh_from_db()

        self.assertEqual(
            self.payment.status,
            Payment.Status.INITIALIZED,
        )
        self.assertEqual(Registration.objects.count(), 0)

    @patch("apps.payments.reconciliation.requests.get")
    def test_amount_mismatch_does_not_change_payment(self, mock_get):
        incorrect_data = {
            **self.verified_data,
            "amount": 100,
        }
        mock_get.return_value = self.make_paystack_response(incorrect_data)

        with self.assertRaises(ReconciliationUnavailable):
            reconcile_payment(
                payment_reference=self.payment.reference,
            )

        self.payment.refresh_from_db()

        self.assertEqual(
            self.payment.status,
            Payment.Status.INITIALIZED,
        )
        self.assertEqual(Registration.objects.count(), 0)

    @patch("apps.payments.reconciliation.requests.get")
    def test_already_resolved_payment_is_skipped(self, mock_get):
        self.payment.status = Payment.Status.PENDING
        self.payment.save(update_fields=["status"])

        result = reconcile_payment(
            payment_reference=self.payment.reference,
        )

        self.assertEqual(result["result"], "skipped")
        mock_get.assert_not_called()

@override_settings(
    PAYSTACK_SECRET_KEY="sk_test_example",
    PAYSTACK_BASE_URL="https://api.paystack.co",
)
class ReconcilePaymentsCommandTests(APITestCase):

    def setUp(self):
        self.attendee = User.objects.create_user(
            username="command_attendee",
            email="command@example.com",
            password="TestPassword123!",
        )

        now = timezone.now()

        self.event = Event.objects.create(
            organizer=self.attendee,
            title="Command Test Conference",
            slug="command-test-conference",
            description="Testing the reconciliation command.",
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
            quantity=1,
            status=TicketHold.Status.ACTIVE,
            expires_at=now + timedelta(minutes=10),
        )

    def create_payment(self):
        return Payment.objects.create(
            hold=self.hold,
            amount_subunit=150000,
            currency="NGN",
            status=Payment.Status.INITIALIZED,
        )

    @patch(
        "apps.payments.management.commands.reconcile_payments.reconcile_payment"
    )
    def test_command_reports_when_no_payments_need_reconciliation(
        self,
        mock_reconcile,
    ):
        output = StringIO()

        call_command(
            "reconcile_payments",
            stdout=output,
        )

        self.assertIn(
            "No unresolved payments need reconciliation.",
            output.getvalue(),
        )
        mock_reconcile.assert_not_called()

    @patch(
        "apps.payments.management.commands.reconcile_payments.reconcile_payment"
    )
    def test_command_only_processes_old_initialized_payments(
        self,
        mock_reconcile,
    ):
        old_payment = self.create_payment()
        recent_payment = self.create_payment()

        Payment.objects.filter(pk=old_payment.pk).update(
            created_at=timezone.now() - timedelta(minutes=5)
        )

        mock_reconcile.return_value = {
            "reference": old_payment.reference,
            "result": "pending",
            "detail": "Still pending.",
        }

        call_command(
            "reconcile_payments",
            minutes=1,
            stdout=StringIO(),
            stderr=StringIO(),
        )

        mock_reconcile.assert_called_once_with(
            payment_reference=old_payment.reference,
        )

        self.assertNotEqual(
            old_payment.reference,
            recent_payment.reference,
        )

    @patch(
        "apps.payments.management.commands.reconcile_payments.reconcile_payment"
    )
    def test_command_respects_batch_limit(self, mock_reconcile):
        payments = [self.create_payment() for _ in range(3)]

        Payment.objects.filter(
            pk__in=[payment.pk for payment in payments]
        ).update(
            created_at=timezone.now() - timedelta(minutes=5)
        )

        mock_reconcile.side_effect = lambda payment_reference: {
            "reference": payment_reference,
            "result": "pending",
            "detail": "Still pending.",
        }

        call_command(
            "reconcile_payments",
            minutes=1,
            limit=2,
            stdout=StringIO(),
            stderr=StringIO(),
        )

        self.assertEqual(mock_reconcile.call_count, 2)

@override_settings(
    PAYSTACK_SECRET_KEY="sk_test_example",
    PAYSTACK_BASE_URL="https://api.paystack.co",
)
class ReconciliationRaceConditionTests(APITestCase):

    def setUp(self):
        self.attendee = User.objects.create_user(
            username="race_attendee",
            email="race@example.com",
            password="TestPassword123!",
        )

        now = timezone.now()

        self.event = Event.objects.create(
            organizer=self.attendee,
            title="Race Condition Conference",
            slug="race-condition-conference",
            description="Testing webhook and reconciliation races.",
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
            status=Payment.Status.INITIALIZED,
        )

        self.verified_data = {
            "id": 987654321,
            "reference": self.payment.reference,
            "status": "success",
            "amount": 300000,
            "currency": "NGN",
        }

    @patch("apps.payments.reconciliation.requests.get")
    def test_late_failed_response_does_not_overwrite_webhook_success(
        self,
        mock_get,
    ):
        from apps.payments.confirmation import confirm_successful_payment

        # Simulate a webhook confirming payment while reconciliation
        # is waiting for Paystack's verification response.
        def confirm_payment_then_return_failure(*args, **kwargs):
            confirm_successful_payment(
                payment_reference=self.payment.reference,
                verified_data=self.verified_data,
            )

            mock_response = Mock()
            mock_response.json.return_value = {
                "status": True,
                "message": "Verification successful",
                "data": {
                    **self.verified_data,
                    "status": "failed",
                },
            }
            return mock_response

        mock_get.side_effect = confirm_payment_then_return_failure

        result = reconcile_payment(
            payment_reference=self.payment.reference,
        )

        self.payment.refresh_from_db()
        self.ticket_tier.refresh_from_db()

        self.assertEqual(result["result"], Payment.Status.SUCCESS)
        self.assertEqual(self.payment.status, Payment.Status.SUCCESS)
        self.assertEqual(self.ticket_tier.sold_quantity, 2)

        self.assertEqual(
            Registration.objects.filter(
                ticket_hold=self.hold,
                status=Registration.Status.CONFIRMED,
            ).count(),
            1,
        )