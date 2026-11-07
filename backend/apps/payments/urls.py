from django.urls import path

from apps.payments.views import PaymentInitializeView
from apps.payments.webhooks import PaystackWebhookView


urlpatterns = [
    path(
        "initialize/",
        PaymentInitializeView.as_view(),
        name="payment-initialize",
    ),
    path(
        "webhook/paystack/",
        PaystackWebhookView.as_view(),
        name="paystack-webhook",
    ),
]