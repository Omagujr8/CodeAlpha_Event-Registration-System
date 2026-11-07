from django.urls import path

from apps.payments.views import PaymentInitializeView


urlpatterns = [
    path(
        "initialize/",
        PaymentInitializeView.as_view(),
        name="payment-initialize",
    ),
]