import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0002_alter_payment_status"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="payment",
            name="status",
            field=models.CharField(
                choices=[
                    ("initialized", "Initialized"),
                    ("pending", "Pending"),
                    ("success", "Success"),
                    ("failed", "Failed"),
                    ("abandoned", "Abandoned"),
                    ("refund_required", "Refund Required"),
                    ("refunded", "Refunded"),
                ],
                db_index=True,
                default="initialized",
                max_length=20,
            ),
        ),
        migrations.CreateModel(
            name="RefundAttempt",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount_subunit", models.PositiveBigIntegerField()),
                ("status", models.CharField(choices=[("pending", "Pending"), ("processed", "Processed"), ("failed", "Failed")], db_index=True, default="pending", max_length=16)),
                ("provider_refund_id", models.CharField(blank=True, max_length=100)),
                ("provider_response", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("processed_at", models.DateTimeField(blank=True, null=True)),
                ("payment", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="refund", to="payments.payment")),
                ("requested_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="requested_refunds", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
