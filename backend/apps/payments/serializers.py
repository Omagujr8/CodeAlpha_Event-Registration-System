from rest_framework import serializers


class PaymentInitializeSerializer(serializers.Serializer):
    hold_reference = serializers.UUIDField()