from django.utils import timezone
from rest_framework import serializers

from apps.events.models import Event, TicketTier
from apps.registrations.models import Registration


class RegistrationSerializer(serializers.ModelSerializer):
    attendee = serializers.PrimaryKeyRelatedField(read_only=True)

    event = serializers.PrimaryKeyRelatedField(
        queryset=Event.objects.all()
    )
    ticket_tier = serializers.PrimaryKeyRelatedField(
        queryset=TicketTier.objects.all()
    )

    class Meta:
        model = Registration
        fields = [
            "id",
            "reference",
            "attendee",
            "event",
            "ticket_tier",
            "status",
            "registered_at",
            "cancelled_at",
        ]
        read_only_fields = [
            "id",
            "reference",
            "attendee",
            "status",
            "registered_at",
            "cancelled_at",
        ]

    def validate(self, attrs):
        event = attrs["event"]
        ticket_tier = attrs["ticket_tier"]
        now = timezone.now()

        if event.status != Event.Status.PUBLISHED:
            raise serializers.ValidationError(
                {"event": "You can only register for a published event."}
            )

        if ticket_tier.event_id != event.id:
            raise serializers.ValidationError(
                {
                    "ticket_tier": (
                        "The selected ticket tier does not belong "
                        "to the selected event."
                    )
                }
            )

        if not ticket_tier.is_active:
            raise serializers.ValidationError(
                {"ticket_tier": "This ticket tier is not active."}
            )

        if (
            ticket_tier.sales_start is not None
            and now < ticket_tier.sales_start
        ):
            raise serializers.ValidationError(
                {"ticket_tier": "Ticket sales have not started."}
            )

        if (
            ticket_tier.sales_end is not None
            and now >= ticket_tier.sales_end
        ):
            raise serializers.ValidationError(
                {"ticket_tier": "Ticket sales have ended."}
            )

        return attrs