from rest_framework.permissions import SAFE_METHODS, BasePermission


class IsOrganizerOrReadOnly(BasePermission):
    """
    Allow read-only access to objects available in the queryset.
    Only the event's organizer or a staff user can modify an event.
    """

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True

        return (
            request.user.is_authenticated
            and (
                obj.organizer_id == request.user.id
                or request.user.is_staff
            )
        )