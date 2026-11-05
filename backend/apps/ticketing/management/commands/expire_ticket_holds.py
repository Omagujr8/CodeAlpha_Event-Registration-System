from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.ticketing.models import TicketHold


class Command(BaseCommand):
    help = "Mark expired ticket holds as expired."

    def handle(self, *args, **options):
        expired_count = TicketHold.objects.filter(
            status=TicketHold.Status.ACTIVE,
            expires_at__lte=timezone.now(),
        ).update(
            status=TicketHold.Status.EXPIRED
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Expired {expired_count} ticket hold(s)."
            )
        )