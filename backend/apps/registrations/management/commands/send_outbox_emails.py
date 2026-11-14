from django.core.management.base import BaseCommand, CommandError

from apps.registrations.email_services import deliver_pending_emails


class Command(BaseCommand):
    help = "Deliver pending registration emails and schedule retries."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        limit = options["limit"]
        if limit < 1 or limit > 1000:
            raise CommandError("--limit must be between 1 and 1000.")

        result = deliver_pending_emails(limit=limit)
        self.stdout.write(
            self.style.SUCCESS(
                "Email delivery: "
                f"{result['sent']} sent, "
                f"{result['deferred']} scheduled for retry, "
                f"{result['failed']} permanently failed, "
                f"{result['checked']} checked."
            )
        )
