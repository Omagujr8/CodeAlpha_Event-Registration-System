from rest_framework import serializers

from apps.events.models import Event, TicketTier


class TicketTierSerializer(serializers.ModelSerializer):
    remaining_quantity = serializers.ReadOnlyField()

    class Meta:
        model = TicketTier
        fields = [
            "id",
            "name",
            "description",
            "price",
            "currency",
            "total_quantity",
            "remaining_quantity",
            "sales_start",
            "sales_end",
            "is_active",
        ]
        read_only_fields = fields


class EventSerializer(serializers.ModelSerializer):
    ticket_tiers = TicketTierSerializer(many=True, read_only=True)

    class Meta:
        model = Event
        fields = [
            "id",
            "title",
            "slug",
            "description",
            "venue",
            "starts_at",
            "ends_at",
            "status",
            "organizer",
            "ticket_tiers",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "organizer",
            "ticket_tiers",
            "created_at",
            "updated_at",
        ]