from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()


class AccountAPITests(APITestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser",
            email="testuser@example.com",
            password="Strong-Test-Password-123!",
        )

        self.register_url = reverse("account-register")
        self.profile_url = reverse("account-profile")

    def test_user_can_register_account(self):
        payload = {
            "username": "newuser",
            "email": "newuser@example.com",
            "password": "Another-Strong-Password-123!",
            "password_confirmation": "Another-Strong-Password-123!",
            "first_name": "New",
            "last_name": "User",
        }

        response = self.client.post(
            self.register_url,
            payload,
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )

        new_user = User.objects.get(username="newuser")

        self.assertTrue(
            new_user.check_password(
                "Another-Strong-Password-123!"
            )
        )

        self.assertNotIn("password", response.data)

    def test_registration_rejects_password_mismatch(self):
        payload = {
            "username": "mismatchuser",
            "email": "mismatch@example.com",
            "password": "Another-Strong-Password-123!",
            "password_confirmation": "Different-Password-123!",
        }

        response = self.client.post(
            self.register_url,
            payload,
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.assertFalse(
            User.objects.filter(username="mismatchuser").exists()
        )

    def test_registration_rejects_duplicate_email(self):
        payload = {
            "username": "duplicateuser",
            "email": self.user.email,
            "password": "Another-Strong-Password-123!",
            "password_confirmation": "Another-Strong-Password-123!",
        }

        response = self.client.post(
            self.register_url,
            payload,
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_anonymous_user_cannot_view_profile(self):
        response = self.client.get(self.profile_url)

        self.assertIn(
            response.status_code,
            [
                status.HTTP_401_UNAUTHORIZED,
                status.HTTP_403_FORBIDDEN,
            ],
        )

    def test_authenticated_user_can_view_own_profile(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.get(self.profile_url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.assertEqual(
            response.data["email"],
            self.user.email,
        )

    def test_authenticated_user_can_update_own_profile(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.patch(
            self.profile_url,
            {
                "first_name": "Emmanuel",
                "last_name": "Omagu",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.user.refresh_from_db()

        self.assertEqual(self.user.first_name, "Emmanuel")
        self.assertEqual(self.user.last_name, "Omagu")

    def test_user_cannot_change_username_or_email_through_profile(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.patch(
            self.profile_url,
            {
                "username": "changedusername",
                "email": "changed@example.com",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.user.refresh_from_db()

        self.assertEqual(self.user.username, "testuser")
        self.assertEqual(self.user.email, "testuser@example.com")

    def test_user_can_obtain_jwt_tokens(self):
        response = self.client.post(
            reverse("token_obtain_pair"),
            {
                "username": "testuser",
                "password": "Strong-Test-Password-123!",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)

    def test_user_can_refresh_access_token(self):
        refresh = RefreshToken.for_user(self.user)

        response = self.client.post(
            reverse("token_refresh"),
            {"refresh": str(refresh)},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.assertIn("access", response.data)