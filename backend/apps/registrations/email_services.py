from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from apps.registrations.models import EmailOutbox


MAX_EMAIL_ATTEMPTS = 5
BASE_RETRY_SECONDS = 60


def enqueue_registration_confirmation(*, registration, tickets):
    attendee = registration.attendee
    event = registration.event
    body = (
        f"Hello {attendee.get_full_name() or attendee.email},\n\n"
        f"Your registration for {event.title} is confirmed.\n"
        f"Ticket reference: {ticket.reference}\n"
        f"Ticket type: {registration.ticket_tier.name}\n"
        "Sign in to your account to retrieve your QR ticket.\n"
    )
    return EmailOutbox.objects.create(
        recipient=attendee.email,
        subject=f"Registration confirmed: {event.title}",
        body=body,
        next_attempt_at=timezone.now(),
    )


def deliver_pending_emails(*, limit=100):
    now = timezone.now()
    sent = failed = deferred = 0
    candidates = list(
        EmailOutbox.objects.filter(
            status=EmailOutbox.Status.PENDING,
            next_attempt_at__lte=now,
        ).order_by("created_at")[:limit].values_list("pk", flat=True)
    )

    for email_id in candidates:
        with transaction.atomic():
            try:
                message = EmailOutbox.objects.select_for_update().get(pk=email_id)
            except EmailOutbox.DoesNotExist:
                continue

            if message.status != EmailOutbox.Status.PENDING:
                continue

            try:
                delivered = send_mail(
                    subject=message.subject,
                    message=message.body,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[message.recipient],
                    fail_silently=False,
                )
                if delivered != 1:
                    raise OSError("Email backend did not confirm delivery.")
            except Exception as exc:
                message.attempts += 1
                message.last_error = str(exc)[:2000]
                if message.attempts >= MAX_EMAIL_ATTEMPTS:
                    message.status = EmailOutbox.Status.FAILED
                    failed += 1
                else:
                    delay = BASE_RETRY_SECONDS * (2 ** (message.attempts - 1))
                    message.next_attempt_at = now + timedelta(seconds=delay)
                    deferred += 1
                message.save(update_fields=[
                    "attempts", "last_error", "status", "next_attempt_at"
                ])
            else:
                message.attempts += 1
                message.status = EmailOutbox.Status.SENT
                message.sent_at = timezone.now()
                message.last_error = ""
                message.save(update_fields=[
                    "attempts", "status", "sent_at", "last_error"
                ])
                sent += 1

    return {"sent": sent, "failed": failed, "deferred": deferred, "checked": len(candidates)}
