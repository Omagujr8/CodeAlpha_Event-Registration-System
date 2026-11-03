from django.urls import path

from apps.accounts.views import (
    AccountProfileView,
    AccountRegistrationView,
)


urlpatterns = [
    path(
        "register/",
        AccountRegistrationView.as_view(),
        name="account-register",
    ),
    path(
        "me/",
        AccountProfileView.as_view(),
        name="account-profile",
    ),
]