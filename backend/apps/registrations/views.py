from django.db import transaction
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, ValidationError
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from apps.registrations.models import Registration
from apps.registrations.serializers import RegistrationSerializer


class RegistrationViewSet(viewsets.ModelViewSet):
    serializer_class = RegistrationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = Registration.objects.select_related(
            "attendee",
            "event",
            "ticket_tier",
        )

        if self.request.user.is_staff:
            return queryset

        return queryset.filter(attendee=self.request.user)

    def create(self, request, *args, **kwargs):
        raise MethodNotAllowed(
            "POST",
            detail=(
                "Registrations are created only after a successful payment "
                "for an active ticket hold."
            ),
        )

    def update(self, request, *args, **kwargs):
        raise MethodNotAllowed("PUT")

    def partial_update(self, request, *args, **kwargs):
        raise MethodNotAllowed("PATCH")

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed("DELETE")

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        with transaction.atomic():
            registration = get_object_or_404(
                self.get_queryset().select_for_update(),
                pk=pk,
            )

            if registration.status == Registration.Status.CANCELLED:
                raise ValidationError(
                    {"status": "This registration is already cancelled."}
                )

            if registration.status == Registration.Status.CONFIRMED:
                raise ValidationError(
                    {
                        "status": (
                            "Confirmed registrations cannot be cancelled "
                            "through this endpoint yet."
                        )
                    }
                )

            registration.status = Registration.Status.CANCELLED
            registration.cancelled_at = timezone.now()
            registration.save(
                update_fields=["status", "cancelled_at"]
            )

        return Response(
            self.get_serializer(registration).data,
            status=status.HTTP_200_OK,
        )