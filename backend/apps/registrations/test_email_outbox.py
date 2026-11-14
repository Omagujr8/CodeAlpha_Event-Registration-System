from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.registrations.email_services import deliver_pending_emails
from apps.registrations.models import EmailOutbox


class EmailOutboxTests(TestCase):
    def create_message(self):
        return EmailOutbox.objects.create(
            recipient="attendee@example.com",
            subject="Registration confirmed",
            body="Your ticket is ready.",
            next_attempt_at=timezone.now(),
        )

    @override_settings(DEFAULT_FROM_EMAIL="events@example.com")
    @patch("apps.registrations.email_services.send_mail", return_value=1)
    def test_pending_email_is_sent(self, mock_send):
        message = self.create_message()
        result = deliver_pending_emails()
        message.refresh_from_db()
        self.assertEqual(result["sent"], 1)
        self.assertEqual(message.status, EmailOutbox.Status.SENT)
        self.assertIsNotNone(message.sent_at)
        self.assertEqual(message.attempts, 1)
        mock_send.assert_called_once()

    @patch("apps.registrations.email_services.send_mail", side_effect=OSError("SMTP unavailable"))
    def test_failed_email_is_scheduled_for_retry(self, mock_send):
        message = self.create_message()
        result = deliver_pending_emails()
        message.refresh_from_db()
        self.assertEqual(result["deferred"], 1)
        self.assertEqual(message.status, EmailOutbox.Status.PENDING)
        self.assertEqual(message.attempts, 1)
        self.assertIn("SMTP unavailable", message.last_error)
        self.assertGreater(message.next_attempt_at, timezone.now())

    @patch("apps.registrations.email_services.send_mail", side_effect=OSError("SMTP unavailable"))
    def test_email_is_marked_failed_after_max_attempts(self, mock_send):
        message = self.create_message()
        message.attempts = 4
        message.save(update_fields=["attempts"])
        result = deliver_pending_emails()
        message.refresh_from_db()
        self.assertEqual(result["failed"], 1)
        self.assertEqual(message.status, EmailOutbox.Status.FAILED)
        self.assertEqual(message.attempts, 5)

    def test_future_retry_is_not_attempted(self):
        message = self.create_message()
        message.next_attempt_at = timezone.now() + timedelta(hours=1)
        message.save(update_fields=["next_attempt_at"])
        result = deliver_pending_emails()
        self.assertEqual(result["checked"], 0)
        self.assertEqual(message.status, EmailOutbox.Status.PENDING)
