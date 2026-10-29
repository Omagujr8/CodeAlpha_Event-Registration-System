from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.events.views import EventViewSet


router = DefaultRouter()
router.register("events", EventViewSet, basename="event")


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include(router.urls)),
]