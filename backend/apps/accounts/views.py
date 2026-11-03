from rest_framework import generics, permissions

from apps.accounts.serializers import (
    AccountProfileSerializer,
    AccountRegistrationSerializer,
)


class AccountRegistrationView(generics.CreateAPIView):
    serializer_class = AccountRegistrationSerializer
    permission_classes = [permissions.AllowAny]


class AccountProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = AccountProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user