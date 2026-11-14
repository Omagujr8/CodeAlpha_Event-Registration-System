from django.contrib import admin

from apps.ticketing.models import IssuedTicket, TicketHold


@admin.register(TicketHold)
class TicketHoldAdmin(admin.ModelAdmin):
    list_display = ("reference", "attendee", "ticket_tier", "quantity", "status", "expires_at")
    list_filter = ("status",)
    search_fields = ("reference", "attendee__email")


@admin.register(IssuedTicket)
class IssuedTicketAdmin(admin.ModelAdmin):
    list_display = ("reference", "registration", "status", "issued_at", "checked_in_at", "checked_in_by")
    list_filter = ("status",)
    search_fields = ("reference", "registration__attendee__email")
