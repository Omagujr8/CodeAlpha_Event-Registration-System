from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from django.urls import reverse

from apps.events.models import Event, TicketTier


User = get_user_model()


class EventAPITests(APITestCase):
    def setUp(self):
        self.organizer = User.objects.create_user(
            username="organizer",
            email="organizer@example.com",
            password="Test-password-123!",
        )
        self.other_user = User.objects.create_user(
            username="otheruser",
            email="other@example.com",
            password="Test-password-456!",
        )

        now = timezone.now()

        self.published_event = Event.objects.create(
            organizer=self.organizer,
            title="Python Conference",
            slug="python-conference",
            description="A conference for Python developers.",
            venue="Minna",
            starts_at=now + timedelta(days=10),
            ends_at=now + timedelta(days=10, hours=4),
            status=Event.Status.PUBLISHED,
        )

        self.draft_event = Event.objects.create(
            organizer=self.organizer,
            title="Draft Workshop",
            slug="draft-workshop",
            description="A workshop that is not public.",
            venue="Minna",
            starts_at=now + timedelta(days=20),
            ends_at=now + timedelta(days=20, hours=3),
            status=Event.Status.DRAFT,
        )

        self.list_url = reverse("event-list")
        self.detail_url = reverse(
            "event-detail",
            args=[self.published_event.id],
        )
        self.draft_url = reverse(
            "event-detail",
            args=[self.draft_event.id],
        )

    def test_anonymous_users_only_see_published_events(self):
        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        event_ids = [item["id"] for item in response.data["results"]]
        self.assertIn(self.published_event.id, event_ids)
        self.assertNotIn(self.draft_event.id, event_ids)

    def test_anonymous_users_cannot_retrieve_draft_events(self):
        response = self.client.get(self.draft_url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_authenticated_user_can_create_an_event(self):
        self.client.force_authenticate(user=self.organizer)

        payload = {
            "title": "Backend Meetup",
            "slug": "backend-meetup",
            "description": "A meetup for backend developers.",
            "venue": "Minna",
            "starts_at": (
                timezone.now() + timedelta(days=30)
            ).isoformat(),
            "ends_at": (
                timezone.now() + timedelta(days=30, hours=2)
            ).isoformat(),
            "organizer": self.other_user.id,
            "status": Event.Status.PUBLISHED,
        }

        response = self.client.post(
            self.list_url,
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        created_event = Event.objects.get(slug="backend-meetup")

        self.assertEqual(created_event.organizer, self.organizer)
        self.assertEqual(created_event.status, Event.Status.DRAFT)

    def test_anonymous_users_cannot_create_events(self):
        payload = {
            "title": "Unauthorized Event",
            "slug": "unauthorized-event",
            "description": "This should not be created.",
            "venue": "Minna",
            "starts_at": (
                timezone.now() + timedelta(days=30)
            ).isoformat(),
            "ends_at": (
                timezone.now() + timedelta(days=30, hours=2)
            ).isoformat(),
        }

        response = self.client.post(
            self.list_url,
            payload,
            format="json",
        )

        self.assertIn(
            response.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )
        self.assertFalse(
            Event.objects.filter(slug="unauthorized-event").exists()
        )

    def test_organizer_can_update_own_draft_event(self):
        self.client.force_authenticate(user=self.organizer)

        response = self.client.patch(
            self.draft_url,
            {"title": "Updated Workshop"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.draft_event.refresh_from_db()
        self.assertEqual(self.draft_event.title, "Updated Workshop")

    def test_other_user_cannot_update_published_event(self):
        self.client.force_authenticate(user=self.other_user)

        response = self.client.patch(
            self.detail_url,
            {"title": "Changed by someone else"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.published_event.refresh_from_db()
        self.assertEqual(
            self.published_event.title,
            "Python Conference",
        )

    def test_event_detail_includes_ticket_tiers(self):
        TicketTier.objects.create(
            event=self.published_event,
            name="Standard",
            description="Standard admission",
            price="5000.00",
            currency="NGN",
            total_quantity=100,
            sold_quantity=10,
        )

        response = self.client.get(self.detail_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["ticket_tiers"]), 1)
        self.assertEqual(
            response.data["ticket_tiers"][0]["name"],
            "Standard",
        )
        self.assertEqual(
            response.data["ticket_tiers"][0]["remaining_quantity"],
            90,
        )