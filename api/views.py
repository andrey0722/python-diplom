from collections.abc import Callable
import logging
from typing import Any, NoReturn, cast, override

from django.contrib.auth.signals import user_logged_in
from django.db.models.query import QuerySet
from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _
import httpx
from rest_framework import status
from rest_framework.authentication import authenticate
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.generics import CreateAPIView
from rest_framework.generics import GenericAPIView
from rest_framework.generics import ListCreateAPIView
from rest_framework.generics import RetrieveAPIView
from rest_framework.generics import UpdateAPIView
from rest_framework.generics import get_object_or_404
from rest_framework.mixins import UpdateModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer
from rest_framework.views import APIView

from .exceptions import MissingIdsError
from .exceptions import ShopUrlLoadError
from .exceptions import TokenConfirmError
from .models import Contact
from .models import Shop
from .models import Token
from .models import User
from .serializers import ContactSerializer
from .serializers import EmailConfirmSerializer
from .serializers import IdSerializer
from .serializers import ItemsSerializer
from .serializers import PasswordResetConfirmSerializer
from .serializers import SendEmailVerificationSerializer
from .serializers import SendPasswordResetSerializer
from .serializers import ShopStateSerializer
from .serializers import ShopUpdateURLSerializer
from .serializers import TokenSerializer
from .serializers import UserLoginSerializer
from .serializers import UserSerializer
from .services import check_email_verify_token
from .services import check_password_reset_token
from .services import retry_get_url
from .services import send_email_verification_mail
from .services import send_password_reset_mail
from .services import update_shop_pricing_yaml
from .services import validate_data
from .services import validate_request

logger = logging.getLogger(__name__)


class TokenConfirmView(GenericAPIView):
    """Base view for validating user confirmation tokens."""

    serializer_class = None
    """Serializer must have 'user' and 'token' fields."""

    validate_token: Callable[[User, str], bool] | None = None

    def post(self, request: Request) -> Response:
        """Validate request data and confirm the provided token.

        Args:
            request (Request): The incoming request object.

        Returns:
            Response: Response indicating token confirmation status.

        Raises:
            TokenConfirmError: If the token is invalid or expired.
        """
        assert self.serializer_class is not None, 'Serializer is not set'
        data = validate_data(self.serializer_class, request.data)
        user: User | None = data['user']
        token: str = data['token']

        assert self.validate_token is not None, 'Token validator is not set'
        if not check_password_reset_token(user, token):
            self.bad_token()
        return self.token_confirmed(data)

    def bad_token(self) -> NoReturn:
        """Handle invalid tokens by raising an error.

        Raises:
            TokenConfirmError: Always raised to indicate invalid token.
        """
        raise TokenConfirmError

    def token_confirmed(self, data: dict[str, Any]) -> Response:  # noqa: ARG002
        """Actions when valid token is provided.

        Args:
            data (dict[str, Any]): Validated token data.

        Returns:
            Response: Final response to the client.
        """
        return Response(_('Token confirmed.'))


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


class EmailConfirmView(TokenConfirmView):
    """View for confirming email with token."""

    serializer_class = EmailConfirmSerializer
    validate_token = check_email_verify_token

    @override
    def token_confirmed(self, data: dict[str, Any]) -> Response:
        """Activate the user account on valid token."""
        user = cast(User, data['user'])
        user.is_active = True
        user.save()
        return Response(_('Email successfully verified.'))


class SendPasswordResetView(APIView):
    """View for sending password reset emails."""

    serializer_class = SendPasswordResetSerializer

    def post(self, request: Request) -> Response:
        """Send a password reset email to user."""
        data = validate_data(self.serializer_class, request.data)
        send_password_reset_mail(request, **data)
        return Response(_('Password reset email is sent if needed.'))


class PasswordResetConfirmView(TokenConfirmView):
    """View for confirming password reset with token."""

    serializer_class = PasswordResetConfirmSerializer
    validate_token = check_password_reset_token

    @override
    def token_confirmed(self, data: dict[str, Any]) -> Response:
        """Update user password on valid token."""
        user = cast(User, data['user'])
        user.set_password(data['password'])
        user.save()
        return Response(_('Password successfully reset.'))


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


class UserInfoView(RetrieveAPIView, UpdateModelMixin):
    """View for user personal info management."""

    serializer_class = UserSerializer
    permission_classes = (IsAuthenticated,)

    @override
    def get_object(self):  # pyright: ignore[reportIncompatibleMethodOverride]
        """Get the current authorized user object.

        Returns:
            User: The current authorized user.
        """
        obj = self.request.user
        self.check_object_permissions(self.request, obj)
        return obj

    def post(self, request, *args, **kwargs):
        """Update user personal information.

        Args:
            request: The request object.
            args: Additional positional arguments.
            kwargs: Additional keyword arguments.

        Returns:
            Response: Updated user information.
        """
        return self.partial_update(request, *args, **kwargs)


class UserContactsView(ListCreateAPIView, UpdateAPIView):
    """View for managing user contacts."""

    queryset = Contact.objects
    serializer_class = ContactSerializer
    permission_classes = (IsAuthenticated,)

    @property
    def user(self) -> User:
        """Get the current authorized user.

        Returns:
            User: The authorized user from the request.
        """
        return cast(User, self.request.user)

    @override
    def get_queryset(self) -> QuerySet:  # pyright: ignore[reportIncompatibleMethodOverride]
        """Get contacts filtered for the current user.

        Returns:
            QuerySet: Contact queryset filtered by current user.
        """
        return self.queryset.filter(user=self.user)

    @override
    def get_object(self):
        """Resolve the object using the ID from request data.

        Returns:
            Contact: The contact object with the ID from request.
        """
        self.kwargs[self.lookup_field] = self._get_id()
        return super().get_object()

    @override
    def perform_create(self, serializer: BaseSerializer):
        """Save a new contact for the current user.

        Args:
            serializer (BaseSerializer): Serializer with validated data.
        """
        serializer.save(user=self.user)

    def delete(self, _request, *_args, **_kwargs):
        """Delete selected contacts by ID list from request.

        Args:
            _request: The request object.
            _args: Additional positional arguments (unused).
            _kwargs: Additional keyword arguments (unused).

        Returns:
            Response: HTTP response to the client.

        Raises:
            MissingIdsError: If any of the requested IDs don't exist.
        """
        item_ids = self._get_items()
        queryset = self.get_queryset().filter(id__in=item_ids)
        count = queryset.count()
        if count != len(item_ids):
            found_ids = set(queryset.values_list('id', flat=True))
            raise MissingIdsError(item_ids - found_ids)
        queryset.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _get_id(self) -> int:
        """Read a single object ID from request data.

        Returns:
            int: The parsed object ID.
        """
        data = validate_request(IdSerializer, self)
        return data['id']

    def _get_items(self) -> set[int]:
        """Read a list of item IDs from request data.

        Returns:
            set[int]: A set of parsed item IDs.
        """
        data = validate_request(ItemsSerializer, self)
        return set(data['items'])


class ShopUpdateView(APIView):
    """View for updating a shop's pricing catalog from a provided URL."""

    serializer_class = ShopUpdateURLSerializer
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        """Validate incoming URL and load shop pricing data.

        Args:
            request (Request): The request object containing shop update URL.

        Returns:
            Response: Success message after updating shop data.

        Raises:
            ShopUrlLoadError: If the URL cannot be fetched or is invalid.
        """
        data = validate_data(self.serializer_class, request.data)
        url: str = data['url']
        pricing = self.load_shop_pricing(url)
        update_shop_pricing_yaml(request.user, url, pricing)
        return Response(_('Shop data updated.'))

    def load_shop_pricing(self, url: str) -> str:
        """Fetch the shop pricing document from the provided URL.

        Args:
            url (str): The URL to fetch pricing data from.

        Returns:
            str: The raw pricing document content.

        Raises:
            ShopUrlLoadError: If the URL request fails or
                non-success status.
        """
        try:
            response = retry_get_url(url)
        except httpx.RequestError as e:
            logger.exception('Shop URL connect error')
            raise ShopUrlLoadError from e
        if not response.is_success:
            raise ShopUrlLoadError
        return response.text


class ShopStateView(RetrieveAPIView, UpdateModelMixin):
    """View for managing a shop's active state."""

    queryset = Shop.objects
    serializer_class = ShopStateSerializer
    permission_classes = (IsAuthenticated,)

    @override
    def get_object(self):  # pyright: ignore[reportIncompatibleMethodOverride]
        """Get the current authorized user's shop.

        Returns:
            Shop: The shop instance associated with the current user.
        """
        user = self.request.user
        obj = get_object_or_404(self.get_queryset(), user=user)
        self.check_object_permissions(self.request, obj)
        return obj

    def post(self, request, *args, **kwargs):
        """Update the shop active state.

        Args:
            request: The request object.
            args: Additional positional arguments.
            kwargs: Additional keyword arguments.

        Returns:
            Response: Updated shop state.
        """
        return self.partial_update(request, *args, **kwargs)
