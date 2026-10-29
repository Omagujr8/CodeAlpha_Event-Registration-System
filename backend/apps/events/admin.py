
from django.contrib import admin

from apps.events.models import Event, TicketTier


class TicketTierInline(admin.TabularInline):
    model = TicketTier
    extra = 1


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "organizer",
        "starts_at",
        "status",
    )
    list_filter = ("status", "starts_at")
    search_fields = ("title", "venue", "organizer__email")
    prepopulated_fields = {"slug": ("title",)}
    inlines = [TicketTierInline]


@admin.register(TicketTier)
class TicketTierAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "event",
        "price",
        "currency",
        "total_quantity",
        "sold_quantity",
        "is_active",
    )
    list_filter = ("currency", "is_active")
    search_fields = ("name", "event__title")
