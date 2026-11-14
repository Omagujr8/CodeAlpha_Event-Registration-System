from django.contrib import admin

from apps.payments.models import Payment, RefundAttempt


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("reference", "hold", "amount_subunit", "currency", "status", "created_at")
    list_filter = ("status", "currency")
    search_fields = ("reference", "provider_transaction_id", "hold__attendee__email")


@admin.register(RefundAttempt)
class RefundAttemptAdmin(admin.ModelAdmin):
    list_display = ("payment", "amount_subunit", "status", "provider_refund_id", "created_at", "processed_at")
    list_filter = ("status",)
    search_fields = ("payment__reference", "provider_refund_id")
    readonly_fields = ("created_at", "updated_at", "processed_at")
