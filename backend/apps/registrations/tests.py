from datetime import timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.events.models import Event, TicketTier
from apps.registrations.models import Registration


User = get_user_model()


class RegistrationAPITests(APITestCase):
    def setUp(self):
        self.attendee = User.objects.create_user(
            username="attendee",
            email="attendee@example.com",
            password="Test-password-123!",
        )
        self.other_attendee = User.objects.create_user(
            username="other",
            email="other@example.com",
            password="Test-password-456!",
        )

        now = timezone.now()

        self.event = Event.objects.create(
            organizer=self.attendee,
            title="Python Conference",
            slug="python-conference",
            description="A conference for Python developers.",
            venue="Minna",
            starts_at=now + timedelta(days=10),
            ends_at=now + timedelta(days=10, hours=4),
            status=Event.Status.PUBLISHED,
        )

        self.tier = TicketTier.objects.create(
            event=self.event,
            name="Standard",
            description="Standard admission",
            price="5000.00",
            currency="NGN",
            total_quantity=100,
            sold_quantity=0,
            is_active=True,
        )

        self.other_event = Event.objects.create(
            organizer=self.other_attendee,
            title="Django Workshop",
            slug="django-workshop",
            description="A Django workshop.",
            venue="Minna",
            starts_at=now + timedelta(days=15),
            ends_at=now + timedelta(days=15, hours=3),
            status=Event.Status.PUBLISHED,
        )

        self.other_tier = TicketTier.objects.create(
            event=self.other_event,
            name="Workshop Ticket",
            description="Workshop admission",
            price="3000.00",
            currency="NGN",
            total_quantity=50,
            sold_quantity=0,
            is_active=True,
        )

        self.list_url = reverse("registration-list")

    def create_registration(self, attendee=None):
        return Registration.objects.create(
            attendee=attendee or self.attendee,
            event=self.event,
            ticket_tier=self.tier,
        )

    def test_anonymous_user_cannot_list_registrations(self):
        response = self.client.get(self.list_url)

        self.assertIn(
            response.status_code,
            [
                status.HTTP_401_UNAUTHORIZED,
                status.HTTP_403_FORBIDDEN,
            ],
        )

    def test_attendee_cannot_create_registration_without_payment(self):
        self.client.force_authenticate(user=self.attendee)

        response = self.client.post(
            self.list_url,
            {
                "event": self.event.id,
                "ticket_tier": self.tier.id,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )
        self.assertEqual(Registration.objects.count(), 0)

    def test_client_cannot_assign_registration_to_another_user(self):
        self.client.force_authenticate(user=self.attendee)

        response = self.client.post(
            self.list_url,
            {
                "event": self.event.id,
                "ticket_tier": self.tier.id,
                "attendee": self.other_attendee.id,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )

        registration = Registration.objects.get(
            reference=response.data["reference"]
        )
        self.assertEqual(registration.attendee, self.attendee)

    def test_rejects_ticket_tier_from_another_event(self):
        self.client.force_authenticate(user=self.attendee)

        response = self.client.post(
            self.list_url,
            {
                "event": self.event.id,
                "ticket_tier": self.other_tier.id,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(Registration.objects.count(), 0)

    def test_rejects_registration_for_draft_event(self):
        draft_event = Event.objects.create(
            organizer=self.attendee,
            title="Private Event",
            slug="private-event",
            description="Not published.",
            venue="Minna",
            starts_at=timezone.now() + timedelta(days=20),
            ends_at=timezone.now() + timedelta(days=20, hours=2),
            status=Event.Status.DRAFT,
        )

        draft_tier = TicketTier.objects.create(
            event=draft_event,
            name="Draft Ticket",
            price="1000.00",
            currency="NGN",
            total_quantity=20,
        )

        self.client.force_authenticate(user=self.attendee)

        response = self.client.post(
            self.list_url,
            {
                "event": draft_event.id,
                "ticket_tier": draft_tier.id,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_attendee_only_sees_own_registrations(self):
        own_registration = self.create_registration(self.attendee)
        self.create_registration(self.other_attendee)

        self.client.force_authenticate(user=self.attendee)

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        references = {
            item["reference"]
            for item in response.data["results"]
        }

        self.assertEqual(references, {str(own_registration.reference)})

    def test_attendee_cannot_retrieve_another_users_registration(self):
        registration = self.create_registration(self.other_attendee)
        detail_url = reverse(
            "registration-detail",
            args=[registration.id],
        )

        self.client.force_authenticate(user=self.attendee)

        response = self.client.get(detail_url)

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_attendee_can_cancel_own_pending_registration(self):
        registration = self.create_registration()
        cancel_url = reverse(
            "registration-cancel",
            args=[registration.id],
        )

        self.client.force_authenticate(user=self.attendee)

        response = self.client.post(cancel_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        registration.refresh_from_db()
        self.assertEqual(
            registration.status,
            Registration.Status.CANCELLED,
        )
        self.assertIsNotNone(registration.cancelled_at)

    def test_attendee_cannot_cancel_another_users_registration(self):
        registration = self.create_registration(self.other_attendee)
        cancel_url = reverse(
            "registration-cancel",
            args=[registration.id],
        )

        self.client.force_authenticate(user=self.attendee)

        response = self.client.post(cancel_url)

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

        registration.refresh_from_db()
        self.assertEqual(
            registration.status,
            Registration.Status.PENDING,
        )

    def test_cannot_cancel_registration_twice(self):
        registration = self.create_registration()
        registration.status = Registration.Status.CANCELLED
        registration.cancelled_at = timezone.now()
        registration.save(
            update_fields=["status", "cancelled_at"]
        )

        cancel_url = reverse(
            "registration-cancel",
            args=[registration.id],
        )

        self.client.force_authenticate(user=self.attendee)

        response = self.client.post(cancel_url)

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_cannot_delete_registration_directly(self):
        registration = self.create_registration()
        detail_url = reverse(
            "registration-detail",
            args=[registration.id],
        )

        self.client.force_authenticate(user=self.attendee)

        response = self.client.delete(detail_url)

        self.assertEqual(
            response.status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )
        self.assertTrue(
            Registration.objects.filter(id=registration.id).exists()
        )