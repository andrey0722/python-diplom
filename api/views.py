import logging
from typing import cast, override

from django.contrib.auth.signals import user_logged_in
from django.db.models.query import QuerySet
from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _
from rest_framework import status
from rest_framework.authentication import authenticate
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.exceptions import NotFound
from rest_framework.generics import CreateAPIView
from rest_framework.generics import ListCreateAPIView
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.generics import UpdateAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer
from rest_framework.views import APIView

from .exceptions import EmailConfirmError
from .models import Contact
from .models import Token
from .models import User
from .serializers import ContactSerializer
from .serializers import EmailConfirmSerializer
from .serializers import IdSerializer
from .serializers import ItemsSerializer
from .serializers import SendEmailVerificationSerializer
from .serializers import TokenSerializer
from .serializers import UserLoginSerializer
from .serializers import UserSerializer
from .services import check_user_token
from .services import send_email_verification_mail
from .services import validate_data
from .services import validate_request

logger = logging.getLogger(__name__)


class UserRegisterView(CreateAPIView):
    """View for user registration."""

    serializer_class = UserSerializer

    @override
    def perform_create(self, serializer: BaseSerializer):
        """Create a new user and send verification email."""
        user = serializer.save()
        send_email_verification_mail(self.request, user)


class SendEmailVerificationView(APIView):
    """View for sending email verification."""

    serializer_class = SendEmailVerificationSerializer

    def post(self, request: Request) -> Response:
        """Send verification email to user.

        Args:
            request (Request): The request object.

        Returns:
            Response: Success message.
        """
        data = validate_data(self.serializer_class, request.data)
        send_email_verification_mail(request, **data)
        return Response(_('Verification email is sent if needed.'))


class EmailConfirmView(APIView):
    """View for confirming email with token."""

    serializer_class = EmailConfirmSerializer

    def post(self, request: Request) -> Response:
        """Confirm user email and activate account.

        Args:
            request (Request): The request object.

        Returns:
            Response: Success message.
        """
        data = validate_data(self.serializer_class, request.data)
        user: User | None = data['user']
        token: str = data['token']
        if not check_user_token(user, token):
            raise EmailConfirmError

        # Email confirmed, activate the user
        user = cast(User, user)
        user.is_active = True
        user.save()
        return Response(_('Email successfully verified.'))


class UserLoginView(APIView):
    """View for user authentication and creating login tokens."""

    serializer_class = UserLoginSerializer

    def post(self, request: Request) -> Response:
        """Authenticate user and return new user API token.

        Args:
            request (Request): The request object.

        Returns:
            Response: The user API token.
        """
        credentials = validate_data(self.serializer_class, request.data)

        user = authenticate(cast(HttpRequest, request), **credentials)
        if user is None:
            raise AuthenticationFailed(_('Invalid email or password.'))
        if not user.is_active:
            raise AuthenticationFailed(_('User inactive or deleted.'))

        token = Token.objects.create(user=user)
        # Update last_login
        user_logged_in.send(self, user=user)

        serializer = TokenSerializer(token)
        return Response(serializer.data)


class UserInfoView(RetrieveUpdateAPIView):
    """View for user personal info management."""

    serializer_class = UserSerializer
    permission_classes = (IsAuthenticated,)

    @override
    def get_object(self):  # pyright: ignore[reportIncompatibleMethodOverride]
        """Return the current authorized user."""
        obj = self.request.user
        self.check_object_permissions(self.request, obj)
        return obj

    def post(self, request, *args, **kwargs):
        """Allow  also POST request for updating user info."""
        return self.patch(request, *args, **kwargs)


class UserContactsView(ListCreateAPIView, UpdateAPIView):
    """View for managing user contacts."""

    queryset = Contact.objects
    serializer_class = ContactSerializer
    permission_classes = (IsAuthenticated,)

    @property
    def user(self) -> User:
        """Return the current authenticated user."""
        return cast(User, self.request.user)

    @override
    def get_queryset(self) -> QuerySet:  # pyright: ignore[reportIncompatibleMethodOverride]
        """Filter contacts for the current user."""
        return self.queryset.filter(user=self.user)

    @override
    def get_object(self):
        """Resolve the object using the ID from request data."""
        self.kwargs[self.lookup_field] = self._get_id()
        return super().get_object()

    @override
    def perform_create(self, serializer: BaseSerializer):
        """Save a new contact for the current user."""
        serializer.save(user=self.user)

    def delete(self, _request, *_args, **_kwargs):
        """Delete selected contacts by ID list."""
        item_ids = self._get_items()
        queryset = self.queryset.filter(id__in=item_ids)
        count = queryset.count()
        if count != len(item_ids):
            raise NotFound
        queryset.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _get_id(self) -> int:
        """Read a single object ID from request data."""
        data = validate_request(IdSerializer, self)
        return data['id']

    def _get_items(self) -> list[int]:
        """Read a list of item IDs from request data."""
        data = validate_request(ItemsSerializer, self)
        return data['items']
