from rest_framework import serializers

from apps.ticketing.models import TicketHold


class TicketHoldCreateSerializer(serializers.Serializer):
    ticket_tier = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1)


class TicketHoldSerializer(serializers.ModelSerializer):
    ticket_tier_name = serializers.CharField(
        source="ticket_tier.name",
        read_only=True,
    )

    class Meta:
        model = TicketHold
        fields = [
            "reference",
            "ticket_tier",
            "ticket_tier_name",
            "quantity",
            "status",
            "expires_at",
            "created_at",
        ]
        read_only_fields = fields