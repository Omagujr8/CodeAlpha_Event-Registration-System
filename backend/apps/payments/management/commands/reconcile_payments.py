from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import APIException

from apps.payments.models import Payment
from apps.payments.reconciliation import reconcile_payment


class Command(BaseCommand):
    help = "Reconcile unresolved Paystack payment attempts."

    def add_arguments(self, parser):
        parser.add_argument(
            "--minutes",
            type=int,
            default=1,
            help="Only check payments at least this many minutes old.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=100,
            help="Maximum number of payments to check in one run.",
        )

    def handle(self, *args, **options):
        minutes = options["minutes"]
        limit = options["limit"]

        if minutes < 0:
            self.stderr.write(self.style.ERROR("--minutes cannot be negative."))
            return

        if limit < 1:
            self.stderr.write(self.style.ERROR("--limit must be at least 1."))
            return

        cutoff = timezone.now() - timedelta(minutes=minutes)
        payments = (
            Payment.objects.filter(
                Q(status=Payment.Status.INITIALIZED)
                | Q(status=Payment.Status.PENDING),
                created_at__lte=cutoff,
            )
            .order_by("created_at")[:limit]
        )
        references = list(payments.values_list("reference", flat=True))

        if not references:
            self.stdout.write(
                self.style.SUCCESS(
                    "No unresolved payments need reconciliation."
                )
            )
            return

        self.stdout.write(
            f"Checking {len(references)} unresolved payment(s)..."
        )

        for reference in references:
            try:
                result = reconcile_payment(payment_reference=reference)
                self.stdout.write(
                    f"{reference}: {result['result']} - {result['detail']}"
                )
            except APIException as exc:
                self.stderr.write(
                    self.style.WARNING(f"{reference}: {exc.detail}")
                )
            except Exception as exc:
                self.stderr.write(
                    self.style.ERROR(f"{reference}: unexpected error - {exc}")
                )

        self.stdout.write(
            self.style.SUCCESS("Reconciliation run completed.")
        )
