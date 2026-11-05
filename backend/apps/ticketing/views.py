from django.shortcuts import get_object_or_404

from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.ticketing.models import TicketHold
from apps.ticketing.serializers import (
    TicketHoldCreateSerializer,
    TicketHoldSerializer,
)
from apps.ticketing.services import (
    create_ticket_hold,
    expire_hold_if_needed,
    release_ticket_hold,
)


class TicketHoldCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        input_serializer = TicketHoldCreateSerializer(
            data=request.data
        )
        input_serializer.is_valid(raise_exception=True)

        hold = create_ticket_hold(
            attendee=request.user,
            ticket_tier_id=input_serializer.validated_data[
                "ticket_tier"
            ],
            quantity=input_serializer.validated_data["quantity"],
        )

        output_serializer = TicketHoldSerializer(hold)

        return Response(
            output_serializer.data,
            status=status.HTTP_201_CREATED,
        )


class TicketHoldDetailView(generics.RetrieveAPIView):
    serializer_class = TicketHoldSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "reference"

    def get_queryset(self):
        return TicketHold.objects.filter(
            attendee=self.request.user
        )

    def retrieve(self, request, *args, **kwargs):
        hold = self.get_object()
        hold = expire_hold_if_needed(hold)

        return Response(
            self.get_serializer(hold).data
        )


class TicketHoldReleaseView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, reference):
        hold = get_object_or_404(
            TicketHold,
            reference=reference,
            attendee=request.user,
        )

        released_hold = release_ticket_hold(
            hold=hold,
            attendee=request.user,
        )

        return Response(
            TicketHoldSerializer(released_hold).data,
            status=status.HTTP_200_OK,
        )