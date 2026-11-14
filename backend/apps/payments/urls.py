from django.urls import path

from apps.payments.views import PaymentInitializeView, PaystackRefundView
from apps.payments.webhooks import PaystackWebhookView


urlpatterns = [
    path("initialize/", PaymentInitializeView.as_view(), name="payment-initialize"),
    path("webhook/paystack/", PaystackWebhookView.as_view(), name="paystack-webhook"),
    path("refunds/<str:payment_reference>/issue/", PaystackRefundView.as_view(), name="paystack-refund-issue"),
]
