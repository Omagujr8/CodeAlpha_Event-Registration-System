from rest_framework import permissions, viewsets
from rest_framework.exceptions import PermissionDenied
from django.db.models import Q
from apps.events.models import Event
from apps.events.permissions import IsOrganizerOrReadOnly
from apps.events.serializers import EventSerializer


class EventViewSet(viewsets.ModelViewSet):
    serializer_class = EventSerializer
    permission_classes = [
        permissions.IsAuthenticatedOrReadOnly,
        IsOrganizerOrReadOnly,
    ]

    def get_queryset(self):
        queryset = (
            Event.objects
            .prefetch_related("ticket_tiers")
            .order_by("starts_at")
        )

        user = self.request.user

        if user.is_authenticated and user.is_staff:
            return queryset

        if user.is_authenticated:
            return queryset.filter(
                Q(status=Event.Status.PUBLISHED)
                | Q(organizer=user)
            ).distinct()

        return queryset.filter(status=Event.Status.PUBLISHED)

    def perform_create(self, serializer):
        if not self.request.user.is_authenticated:
            raise PermissionDenied(
                "You must be logged in to create an event."
            )

        serializer.save(organizer=self.request.user)