from django.urls import path

from apps.ticketing.views import (
    MyTicketDetailView,
    TicketCheckInView,
    TicketHoldCreateView,
    TicketHoldDetailView,
    TicketHoldReleaseView,
)


urlpatterns = [
    path("tickets/<uuid:reference>/", MyTicketDetailView.as_view(), name="issued-ticket-detail"),
    path("check-in/", TicketCheckInView.as_view(), name="ticket-check-in"),
    path("holds/", TicketHoldCreateView.as_view(), name="ticket-hold-create"),
    path("holds/<uuid:reference>/", TicketHoldDetailView.as_view(), name="ticket-hold-detail"),
    path("holds/<uuid:reference>/release/", TicketHoldReleaseView.as_view(), name="ticket-hold-release"),
]
