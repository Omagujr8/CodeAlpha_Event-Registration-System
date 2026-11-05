from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)
from apps.events.views import EventViewSet
from apps.registrations.views import RegistrationViewSet

router = DefaultRouter()
router.register("events", EventViewSet, basename="event")
router.register(
    "registrations",
    RegistrationViewSet,
    basename="registration",
)


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/", include(router.urls)),
    path("api/accounts/", include("apps.accounts.urls")),
    path("api/ticketing/",include("apps.ticketing.urls")),
]