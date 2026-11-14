# Generated for issued attendee tickets.
import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("registrations", "0002_registration_ticket_hold"),
        ("ticketing", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="IssuedTicket",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("reference", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("status", models.CharField(choices=[("issued", "Issued"), ("checked_in", "Checked in"), ("revoked", "Revoked")], db_index=True, default="issued", max_length=20)),
                ("issued_at", models.DateTimeField(auto_now_add=True)),
                ("checked_in_at", models.DateTimeField(blank=True, null=True)),
                ("checked_in_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="ticket_checkins", to=settings.AUTH_USER_MODEL)),
                ("registration", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="tickets", to="registrations.registration")),
            ],
            options={
                "ordering": ["-issued_at"],
                "indexes": [models.Index(fields=["registration", "status"], name="ticket_reg_status_idx")],
            },
        ),
    ]
