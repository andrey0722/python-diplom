import logging
from typing import Any, NoReturn, cast, override

from django.contrib.auth.signals import user_logged_in
from django.db.models import Exists
from django.db.models import OuterRef
from django.db.models import Prefetch
from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _
from rest_framework import status
from rest_framework.authentication import authenticate
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.generics import CreateAPIView
from rest_framework.generics import DestroyAPIView
from rest_framework.generics import GenericAPIView
from rest_framework.generics import ListAPIView
from rest_framework.generics import ListCreateAPIView
from rest_framework.generics import RetrieveAPIView
from rest_framework.generics import UpdateAPIView
from rest_framework.mixins import UpdateModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer
from rest_framework.views import APIView

from .exceptions import TokenConfirmError
from .filters import CategoryFilter
from .filters import ShopFilter
from .filters import ShopOfferFilter
from .mixins import FilterByIdsListMixin
from .mixins import GetObjectByAuthUserMixin
from .mixins import GetQuerySetByAuthUserMixin
from .mixins import ListRetrieveModelMixin
from .models import Basket
from .models import Category
from .models import Contact
from .models import Order
from .models import OrderItem
from .models import OrderState
from .models import PlacedOrder
from .models import Shop
from .models import ShopOffer
from .models import Token
from .models import User
from .permissions import UserOwnsShop
from .serializers import AddToBasketSerializer
from .serializers import CategorySerializer
from .serializers import ContactSerializer
from .serializers import EditBasketSerializer
from .serializers import EmailConfirmSerializer
from .serializers import FilteredOrderSerializer
from .serializers import IdSerializer
from .serializers import OrderSerializer
from .serializers import PasswordResetConfirmSerializer
from .serializers import PlaceOrderSerializer
from .serializers import SendEmailVerificationSerializer
from .serializers import SendPasswordResetSerializer
from .serializers import ShopOfferSerializer
from .serializers import ShopSerializer
from .serializers import ShopUpdateURLSerializer
from .serializers import TokenSerializer
from .serializers import UserLoginSerializer
from .serializers import UserSerializer
from .serializers import VerificationSentSerializer
from .services import add_to_basket
from .services import change_order_state
from .services import check_email_verify_token
from .services import check_password_reset_token
from .services import checkout_basket
from .services import edit_basket
from .services import retry_get_url
from .services import send_email_verification_mail
from .services import send_password_reset_mail
from .services import serialize_dict
from .services import update_shop_pricing_yaml
from .services import validate_request
from .services import validate_view

logger = logging.getLogger(__name__)


class SendVerificationView(GenericAPIView):
    """View for sending verification emails."""

    serializer_class = None
    response_message = _('Verification is sent if needed.')

    @staticmethod
    def send_mail(request: Request, *args: Any, **kwargs: Any) -> str | None:
        """Send verification email to the user.

        This method must be implemented by subclasses to handle the actual
        email sending logic. It should generate and send a verification
        token to the user based on the provided request and data.

        Args:
            request (Request): The HTTP request object.
            *args (Any): Additional positional arguments.
            **kwargs (Any): Additional keyword arguments containing user data.

        Returns:
            str | None: Verification token if generated.
        """
        raise NotImplementedError

    def post(self, request: Request) -> Response:
        """Validate the request and send a verification email.

        Args:
            request (Request): The incoming request object.

        Returns:
            Response: Response containing verification status and token info.
        """
        assert self.serializer_class is not None, 'Serializer is not set'

        data = validate_request(self.serializer_class, request)
        token = self.send_mail(request, **data)
        data = serialize_dict(
            VerificationSentSerializer,
            status=self.response_message,
            token=token,
        )
        return Response(data)


class TokenConfirmView(GenericAPIView):
    """Base view for validating user confirmation tokens."""

    serializer_class = None
    """Serializer must have 'user' and 'token' fields."""

    @staticmethod
    def validate_token(user: User | None, token: str | None) -> bool:
        """Validate the provided token for the given user.

        This method must be implemented by subclasses to handle the actual
        token validation logic. It should check if the token is valid for
        the specified user and perform any necessary token cleanup.

        Args:
            user (User | None): The user object to validate the token for.
            token (str | None): The token string to validate.

        Returns:
            True if the token is valid, False otherwise.
        """
        raise NotImplementedError

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
        data = validate_request(self.serializer_class, request)
        user: User | None = data['user']
        token: str = data['token']

        if self.validate_token(user, token):
            return self.token_confirmed(data)
        return self.bad_token()

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
        """Create a new user and send verification email.

        Args:
            serializer (BaseSerializer): Serializer with validated user data.
        """
        user = serializer.save()
        send_email_verification_mail(self.request, user)


class SendEmailVerificationView(SendVerificationView):
    """View for sending email verification emails."""

    serializer_class = SendEmailVerificationSerializer
    response_message = _('Verification email is sent if needed.')
    send_mail = staticmethod(send_email_verification_mail)


class EmailConfirmView(TokenConfirmView):
    """View for confirming email with token."""

    serializer_class = EmailConfirmSerializer
    validate_token = staticmethod(check_email_verify_token)

    @override
    def token_confirmed(self, data: dict[str, Any]) -> Response:
        """Activate the user account on valid token.

        Args:
            data (dict[str, Any]): Validated token data.

        Returns:
            Response: Email verification success response.
        """
        user = cast(User, data['user'])
        user.is_active = True
        user.save(update_fields=['is_active'])
        return Response(_('Email successfully verified.'))


class SendPasswordResetView(SendVerificationView):
    """View for sending password reset emails."""

    serializer_class = SendPasswordResetSerializer
    response_message = _('Password reset email is sent if needed.')
    send_mail = staticmethod(send_password_reset_mail)


class PasswordResetConfirmView(TokenConfirmView):
    """View for confirming password reset with token."""

    serializer_class = PasswordResetConfirmSerializer
    validate_token = staticmethod(check_password_reset_token)

    @override
    def token_confirmed(self, data: dict[str, Any]) -> Response:
        """Update user password on valid token.

        Args:
            data (dict[str, Any]): Validated token data.

        Returns:
            Response: Password reset success response.
        """
        user = cast(User, data['user'])
        user.set_password(data['password'])
        user.save(update_fields=['password'])
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
        credentials = validate_request(self.serializer_class, request)

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

    def post(self, request: Request) -> Response:
        """Update user personal information.

        Args:
            request (Request): The request object.

        Returns:
            Response: Updated user information.
        """
        return self.partial_update(request)


class UserContactsView(
    GetQuerySetByAuthUserMixin,
    FilterByIdsListMixin,
    ListCreateAPIView,
    UpdateAPIView,
):
    """View for managing user contacts."""

    queryset = Contact.objects
    serializer_class = ContactSerializer
    permission_classes = (IsAuthenticated,)

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
        serializer.save(user=self.request.user)

    def delete(self, request: Request) -> Response:  # noqa: ARG002
        """Delete selected contacts by ID list from request.

        Args:
            request (Request): The request object.

        Returns:
            Response: HTTP response to the client.
        """
        self.filter_by_ids().delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _get_id(self) -> int:
        """Read a single object ID from request data.

        Returns:
            int: The parsed object ID.
        """
        data = validate_view(IdSerializer, self)
        return data['id']


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
        data = validate_request(self.serializer_class, request)
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
        """
        response = retry_get_url(url)
        return response.text


class ShopStateView(
    GetObjectByAuthUserMixin,
    RetrieveAPIView,
    UpdateModelMixin,
):
    """View for managing a shop's active state."""

    queryset = Shop.objects
    serializer_class = ShopSerializer
    permission_classes = (IsAuthenticated, UserOwnsShop)

    def post(self, request, *args, **kwargs):
        """Update the shop active state.

        Args:
            request (object): The request object.
            *args (object): Additional positional arguments.
            **kwargs (object): Additional keyword arguments.

        Returns:
            Response: Updated shop state.
        """
        return self.partial_update(request, *args, **kwargs)


class ShopOrdersView(ListRetrieveModelMixin):
    """View for shop owners to inspect orders containing their items."""

    queryset = PlacedOrder.objects
    serializer_class = FilteredOrderSerializer
    permission_classes = (IsAuthenticated, UserOwnsShop)

    @override
    def get_queryset(self):  # pyright: ignore[reportIncompatibleMethodOverride]
        """Return orders containing items from the current user's shop.

        Returns:
            QuerySet: Orders prefetched with only the shop's matching items.
        """
        user_id = self.request.user.pk

        # Filter only order items from the current shop
        items = OrderItem.objects.filter(shop_offer__shop__user_id=user_id)

        # Exclude orders with no matched order items
        items_not_empty = Exists(items.filter(order=OuterRef('pk')))

        # Save filtered items to separate attribute for each order
        filtered_items = Prefetch('items', items, to_attr='filtered_items')

        queryset = cast(QuerySet, super().get_queryset())
        return (
            queryset.filter(items_not_empty)
            .prefetch_related(filtered_items)
            .order_by('pk')
        )


class ShopListView(ListAPIView):
    """List view for shops with optional name filtering."""

    queryset = Shop.objects.filter(is_active=True)
    serializer_class = ShopSerializer
    filterset_class = ShopFilter


class CategoryListView(ListAPIView):
    """List view for product categories with optional name filtering."""

    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    filterset_class = CategoryFilter


class ShopOfferListView(ListAPIView):
    """List view for shop offers with optional shop and category filtering."""

    queryset = ShopOffer.objects.select_related(
        'shop', 'product', 'product__category'
    ).filter(shop__is_active=True)
    serializer_class = ShopOfferSerializer
    filterset_class = ShopOfferFilter


class BasketView(
    GetObjectByAuthUserMixin,
    FilterByIdsListMixin,
    RetrieveAPIView,
):
    """View for managing the user's shopping basket."""

    queryset = Basket.objects.prefetch_related('items')
    serializer_class = OrderSerializer
    permission_classes = (IsAuthenticated,)

    items_queryset = OrderItem.objects.filter(order__state=OrderState.BASKET)

    def post(self, request: Request) -> Response:
        """Add items to the user's basket.

        Args:
            request (Request): The request object containing items to add.

        Returns:
            Response: The updated basket contents.
        """
        data = validate_request(AddToBasketSerializer, request)
        add_to_basket(request.user, data['items'])
        return self.get(request)

    def put(self, request: Request) -> Response:
        """Update quantities of items in the user's basket.

        Args:
            request (Request): The request object containing items to update.

        Returns:
            Response: The updated basket contents.
        """
        data = validate_request(EditBasketSerializer, request)
        edit_basket(request.user, data['items'])
        return self.get(request)

    def delete(self, request: Request) -> Response:  # noqa: ARG002
        """Delete specified items from the user's basket.

        Deletes order items by ID from the user's basket.

        Args:
            request (Request): The request object (unused).

        Returns:
            Response: Empty response with 204 status.
        """
        queryset = self.items_queryset.filter(order__user=self.request.user)
        self.filter_by_ids(queryset).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class UserOrderView(
    GetQuerySetByAuthUserMixin,
    ListRetrieveModelMixin,
    DestroyAPIView,
):
    """View for managing user orders and placing new orders."""

    queryset = PlacedOrder.objects
    serializer_class = OrderSerializer
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        """Create an order from user's basket or reopen inactive order.

        Args:
            request (Request): The incoming request.

        Returns:
            Response: Confirmation that the order was placed.
        """
        data = validate_request(PlaceOrderSerializer, request)
        order: Order = data['id']
        contact: Contact = data['contact']
        if order.state == OrderState.BASKET:
            order = checkout_basket(order, contact, request)
        else:
            change_order_state(order, OrderState.NEW, contact, request)
        return self.get(request, order.pk)

    @override
    def perform_destroy(self, instance: PlacedOrder) -> None:
        """Cancel the order through the state transition service.

        Args:
            instance (PlacedOrder): The order being deleted by the API.
        """
        change_order_state(instance, OrderState.CANCELLED, None, self.request)
