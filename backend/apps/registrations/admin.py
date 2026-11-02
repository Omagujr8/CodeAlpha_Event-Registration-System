from django.contrib import admin

from apps.registrations.models import Registration


@admin.register(Registration)
class RegistrationAdmin(admin.ModelAdmin):
    list_display = (
        "reference",
        "attendee",
        "event",
        "ticket_tier",
        "status",
        "registered_at",
    )
    list_filter = ("status", "registered_at")
    search_fields = (
        "reference",
        "attendee__email",
        "event__title",
    )
    readonly_fields = (
        "reference",
        "registered_at",
        "cancelled_at",
    )
    list_select_related = (
        "attendee",
        "event",
        "ticket_tier",
    )