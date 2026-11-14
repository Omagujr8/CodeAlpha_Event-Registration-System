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

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.core import signing

from apps.ticketing.models import IssuedTicket
from apps.ticketing.ticket_services import build_ticket_qr_svg, resolve_ticket_token


class MyTicketDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, reference):
        ticket = get_object_or_404(
            IssuedTicket.objects.select_related(
                "registration__event", "registration__ticket_tier"
            ),
            reference=reference,
            registration__attendee=request.user,
        )
        return Response({
            "reference": str(ticket.reference),
            "status": ticket.status,
            "issued_at": ticket.issued_at,
            "checked_in_at": ticket.checked_in_at,
            "event": ticket.registration.event.title,
            "ticket_tier": ticket.registration.ticket_tier.name,
            "qr_svg": build_ticket_qr_svg(ticket),
        })


class TicketCheckInView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        token = request.data.get("token")
        if not isinstance(token, str) or not token.strip():
            raise ValidationError({"token": "A QR ticket token is required."})

        try:
            ticket = resolve_ticket_token(token)
        except (signing.BadSignature, IssuedTicket.DoesNotExist, ValueError, TypeError):
            raise ValidationError({"token": "This ticket QR code is invalid."})

        event = ticket.registration.event
        if not (request.user.is_staff or event.organizer_id == request.user.id):
            raise PermissionDenied("Only the event organizer or staff can check in tickets.")

        with transaction.atomic():
            ticket = IssuedTicket.objects.select_for_update().select_related(
                "registration"
            ).get(pk=ticket.pk)

            if ticket.status == IssuedTicket.Status.REVOKED:
                raise ValidationError({"ticket": "This ticket has been revoked."})
            if ticket.status == IssuedTicket.Status.CHECKED_IN:
                raise ValidationError({"ticket": "This ticket has already been checked in."})
            if ticket.registration.status != ticket.registration.Status.CONFIRMED:
                raise ValidationError({"ticket": "This registration is not confirmed."})

            ticket.status = IssuedTicket.Status.CHECKED_IN
            ticket.checked_in_at = timezone.now()
            ticket.checked_in_by = request.user
            ticket.save(update_fields=["status", "checked_in_at", "checked_in_by"])

        return Response({
            "detail": "Ticket checked in successfully.",
            "ticket_reference": str(ticket.reference),
            "checked_in_at": ticket.checked_in_at,
        }, status=status.HTTP_200_OK)
