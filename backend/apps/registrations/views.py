from django.db import transaction
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

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

    def perform_create(self, serializer):
        serializer.save(attendee=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)

        headers = self.get_success_headers(serializer.data)

        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED,
            headers=headers,
        )

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        with transaction.atomic():
            registration = (
                self.get_queryset()
                .select_for_update()
                .get(pk=pk)
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