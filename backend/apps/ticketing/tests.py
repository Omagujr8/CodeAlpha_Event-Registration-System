from datetime import timedelta

import redis

from django.conf import settings
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.events.models import Event, TicketTier
from apps.ticketing.models import TicketHold
from apps.ticketing.redis_client import redis_client


class TicketHoldAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.user = User.objects.create_user(
            username="attendee",
            email="attendee@example.com",
            password="TestPassword123!",
        )

        self.event = Event.objects.create(
            organizer=self.user,
            title="Backend Conference",
            slug="backend-conference",
            description="A backend development event.",
            venue="Minna",
            starts_at=timezone.now() + timedelta(days=10),
            ends_at=timezone.now() + timedelta(days=11),
            status=Event.Status.PUBLISHED,
        )

        self.tier = TicketTier.objects.create(
            event=self.event,
            name="Regular",
            price="5000.00",
            currency="NGN",
            total_quantity=5,
            sold_quantity=0,
            is_active=True,
        )

        self.client.force_authenticate(user=self.user)

    def tearDown(self):
        # Remove Redis keys created by these tests.
        for hold in TicketHold.objects.all():
            redis_client.delete(
                f"ticket_hold:{hold.reference}"
            )

    def create_hold(self, quantity=1):
        return self.client.post(
            "/api/ticketing/holds/",
            {
                "ticket_tier": self.tier.id,
                "quantity": quantity,
            },
            format="json",
        )

    def test_attendee_can_create_ticket_hold(self):
        response = self.create_hold(quantity=2)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["quantity"], 2)
        self.assertEqual(response.data["status"], "active")

        hold = TicketHold.objects.get(
            reference=response.data["reference"]
        )

        self.assertEqual(hold.attendee, self.user)
        self.assertEqual(hold.ticket_tier, self.tier)

    def test_hold_expires_after_ten_minutes(self):
        response = self.create_hold()

        self.assertEqual(response.status_code, 201)

        hold = TicketHold.objects.get(
            reference=response.data["reference"]
        )

        expected_expiry = (
            hold.created_at
            + timedelta(
                seconds=settings.TICKET_HOLD_DURATION_SECONDS
            )
        )

        self.assertAlmostEqual(
            hold.expires_at.timestamp(),
            expected_expiry.timestamp(),
            delta=2,
        )

        redis_key = f"ticket_hold:{hold.reference}"

        self.assertTrue(redis_client.exists(redis_key))

        ttl = redis_client.ttl(redis_key)

        self.assertGreater(ttl, 0)
        self.assertLessEqual(
            ttl,
            settings.TICKET_HOLD_DURATION_SECONDS,
        )

    def test_cannot_reserve_more_than_available_inventory(self):
        response = self.create_hold(quantity=6)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(TicketHold.objects.count(), 0)

    def test_active_holds_reduce_available_inventory(self):
        first_response = self.create_hold(quantity=3)

        self.assertEqual(first_response.status_code, 201)

        second_response = self.create_hold(quantity=3)

        self.assertEqual(second_response.status_code, 400)

    def test_expired_hold_does_not_block_new_reservation(self):
        response = self.create_hold(quantity=5)

        self.assertEqual(response.status_code, 201)

        hold = TicketHold.objects.get(
            reference=response.data["reference"]
        )

        hold.expires_at = timezone.now() - timedelta(seconds=1)
        hold.save(update_fields=["expires_at"])

        second_response = self.create_hold(quantity=5)

        self.assertEqual(second_response.status_code, 201)

    def test_attendee_can_release_own_hold(self):
        response = self.create_hold()

        reference = response.data["reference"]

        release_response = self.client.post(
            f"/api/ticketing/holds/{reference}/release/"
        )

        self.assertEqual(release_response.status_code, 200)
        self.assertEqual(
            release_response.data["status"],
            "released",
        )

    def test_attendee_can_view_own_hold(self):
        response = self.create_hold()

        reference = response.data["reference"]

        detail_response = self.client.get(
            f"/api/ticketing/holds/{reference}/"
        )

        self.assertEqual(detail_response.status_code, 200)

    def test_attendee_cannot_view_another_users_hold(self):
        response = self.create_hold()

        reference = response.data["reference"]

        another_user = User.objects.create_user(
            username="another",
            email="another@example.com",
            password="AnotherPassword123!",
        )

        self.client.force_authenticate(user=another_user)

        detail_response = self.client.get(
            f"/api/ticketing/holds/{reference}/"
        )

        self.assertEqual(detail_response.status_code, 404)

    def test_inactive_ticket_tier_cannot_be_reserved(self):
        self.tier.is_active = False
        self.tier.save(update_fields=["is_active"])

        response = self.create_hold()

        self.assertEqual(response.status_code, 400)

    def test_draft_event_cannot_be_reserved(self):
        self.event.status = Event.Status.DRAFT
        self.event.save(update_fields=["status"])

        response = self.create_hold()

        self.assertEqual(response.status_code, 400)
from apps.registrations.models import Registration
from apps.ticketing.models import IssuedTicket
from apps.ticketing.ticket_services import build_ticket_token


class IssuedTicketAPITests(TestCase):
    def setUp(self):
        self.attendee = User.objects.create_user(username="ticket_attendee", email="ticket-attendee@example.com", password="TestPassword123!")
        self.organizer = User.objects.create_user(username="ticket_organizer", email="ticket-organizer@example.com", password="TestPassword123!")
        now = timezone.now()
        self.event = Event.objects.create(organizer=self.organizer, title="Ticketed Conference", slug="ticketed-conference", description="Ticket test event.", venue="Minna", starts_at=now + timedelta(days=5), ends_at=now + timedelta(days=6), status=Event.Status.PUBLISHED)
        self.tier = TicketTier.objects.create(event=self.event, name="General", price="1000.00", currency="NGN", total_quantity=10, sold_quantity=2)
        self.hold = TicketHold.objects.create(attendee=self.attendee, ticket_tier=self.tier, quantity=2, status=TicketHold.Status.CONVERTED, expires_at=now + timedelta(minutes=10))
        self.registration = Registration.objects.create(attendee=self.attendee, event=self.event, ticket_tier=self.tier, ticket_hold=self.hold, status=Registration.Status.CONFIRMED)
        self.ticket = IssuedTicket.objects.create(registration=self.registration)
        self.client = APIClient()

    def test_attendee_can_retrieve_own_qr_ticket(self):
        self.client.force_authenticate(user=self.attendee)
        response = self.client.get("/api/ticketing/tickets/{}/".format(self.ticket.reference))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], IssuedTicket.Status.ISSUED)
        self.assertIn("<svg", response.data["qr_svg"])

    def test_attendee_cannot_retrieve_another_users_ticket(self):
        another = User.objects.create_user(username="ticket_other", email="ticket-other@example.com", password="TestPassword123!")
        self.client.force_authenticate(user=another)
        response = self.client.get("/api/ticketing/tickets/{}/".format(self.ticket.reference))
        self.assertEqual(response.status_code, 404)

    def test_organizer_can_check_in_ticket_once(self):
        self.client.force_authenticate(user=self.organizer)
        token = build_ticket_token(self.ticket)
        response = self.client.post("/api/ticketing/check-in/", {"token": token}, format="json")
        self.assertEqual(response.status_code, 200)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, IssuedTicket.Status.CHECKED_IN)
        self.assertEqual(self.ticket.checked_in_by, self.organizer)
        duplicate = self.client.post("/api/ticketing/check-in/", {"token": token}, format="json")
        self.assertEqual(duplicate.status_code, 400)

    def test_unrelated_user_cannot_check_in_ticket(self):
        another = User.objects.create_user(username="unrelated", email="unrelated@example.com", password="TestPassword123!")
        self.client.force_authenticate(user=another)
        response = self.client.post("/api/ticketing/check-in/", {"token": build_ticket_token(self.ticket)}, format="json")
        self.assertEqual(response.status_code, 403)
