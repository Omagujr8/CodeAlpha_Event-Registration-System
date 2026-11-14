from django.contrib import admin

from apps.registrations.models import EmailOutbox, Registration


@admin.register(Registration)
class RegistrationAdmin(admin.ModelAdmin):
    list_display = ("reference", "attendee", "event", "ticket_tier", "status", "registered_at")
    list_filter = ("status",)
    search_fields = ("reference", "attendee__email", "event__title")


@admin.register(EmailOutbox)
class EmailOutboxAdmin(admin.ModelAdmin):
    list_display = ("recipient", "subject", "status", "attempts", "next_attempt_at", "sent_at")
    list_filter = ("status",)
    search_fields = ("recipient", "subject")
    readonly_fields = ("created_at", "sent_at")
