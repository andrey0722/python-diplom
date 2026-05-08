import logging
from typing import Any, NoReturn, cast, override

from django.contrib.auth.signals import user_logged_in
from django.db.models import Exists
from django.db.models import OuterRef
from django.db.models import Prefetch
from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema
from drf_spectacular.utils import extend_schema_view
from rest_framework import status
from rest_framework.authentication import authenticate
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.exceptions import NotAuthenticated
from rest_framework.exceptions import NotFound
from rest_framework.exceptions import PermissionDenied
from rest_framework.generics import CreateAPIView
from rest_framework.generics import GenericAPIView
from rest_framework.generics import ListAPIView
from rest_framework.generics import ListCreateAPIView
from rest_framework.generics import RetrieveAPIView
from rest_framework.generics import RetrieveDestroyAPIView
from rest_framework.generics import UpdateAPIView
from rest_framework.mixins import UpdateModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer
from rest_framework.views import APIView

from .authentication import TokenAuthentication
from .exceptions import BasketCheckoutError
from .exceptions import InvalidCredentialsError
from .exceptions import InvalidOrderStateTransitionError
from .exceptions import LoginInactiveError
from .exceptions import MissingIdsError
from .exceptions import TokenConfirmError
from .exceptions import WebRequestConnectError
from .exceptions import WebRequestResponseStatusError
from .exceptions import YAMLParsingError
from .filters import CategoryFilter
from .filters import ShopFilter
from .filters import ShopOfferFilter
from .mixins import FilterByIdsListMixin
from .mixins import GetObjectByAuthUserMixin
from .mixins import GetQuerySetByAuthUserMixin
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
from .schema import data_response_dict
from .schema import error_response_dict
from .schema import message_response_dict
from .schema import validation_response_dict
from .serializers import AddToBasketSerializer
from .serializers import CategorySerializer
from .serializers import ContactSerializer
from .serializers import EditBasketSerializer
from .serializers import EmailConfirmSerializer
from .serializers import FilteredOrderSerializer
from .serializers import IdSerializer
from .serializers import ItemsSerializer
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
from .services import reset_user_password
from .services import retry_get_url
from .services import serialize_dict
from .services import update_shop_pricing_yaml
from .services import validate_request
from .services import validate_view
from .services import verify_user_email

logger = logging.getLogger(__name__)


@extend_schema(
    description=_('Request a verification email message.'),
    responses=message_response_dict(_('Verification is sent if needed.')),
)
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


@extend_schema(
    description=_('Confirm a user token and perform required action.'),
    responses={
        **message_response_dict(_('Token confirmed.')),
        **error_response_dict(TokenConfirmError),
    },
)
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
            bool: True if the token is valid, False otherwise.
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


@extend_schema(
    description=_(
        'Register a new user and send an email verification message.'
    ),
    responses={
        **data_response_dict(
            serializer=UserSerializer,
            status_code=status.HTTP_201_CREATED,
        ),
        **validation_response_dict(
            field='email',
            code='unique',
            message=_('User with this email address already exists.'),
        ),
    },
)
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
        verify_user_email(self.request, user)


@extend_schema(
    description=_('Request an email verification to activate account.'),
)
class SendEmailVerificationView(SendVerificationView):
    """View for sending email verification emails."""

    serializer_class = SendEmailVerificationSerializer
    response_message = _('Verification email is sent if needed.')
    send_mail = staticmethod(verify_user_email)


@extend_schema(
    description=_(
        'Confirm the email verification token and activate the account.'
    ),
)
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


@extend_schema(
    description=_('Request a password reset email for an active account.'),
)
class SendPasswordResetView(SendVerificationView):
    """View for sending password reset emails."""

    serializer_class = SendPasswordResetSerializer
    response_message = _('Password reset email is sent if needed.')
    send_mail = staticmethod(reset_user_password)


@extend_schema(
    description=_('Confirm the password reset token and set a new password.'),
)
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
        user.last_login = timezone.now()
        user.save(update_fields=['password', 'last_login'])
        return Response(_('Password successfully reset.'))


@extend_schema(
    description=_('Enter user credentials and acquire a new API token.'),
    responses={
        **data_response_dict(TokenSerializer),
        **error_response_dict(InvalidCredentialsError, LoginInactiveError),
    },
)
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
            raise InvalidCredentialsError
        if not user.is_active:
            raise LoginInactiveError

        token = Token.objects.create(user=user)
        # Update last_login
        user_logged_in.send(self, user=user)

        serializer = TokenSerializer(token)
        return Response(serializer.data)


@extend_schema(
    description=_('Get the current user profile info.'),
    responses={
        **data_response_dict(UserSerializer),
        **error_response_dict(AuthenticationFailed, NotAuthenticated),
    },
)
class UserInfoView(RetrieveAPIView, UpdateModelMixin):
    """View for user personal info management."""

    serializer_class = UserSerializer
    authentication_classes = (TokenAuthentication,)
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

    @extend_schema(description=_('Edit the current user profile info.'))
    def post(self, request: Request) -> Response:
        """Update user personal information.

        Args:
            request (Request): The request object.

        Returns:
            Response: Updated user information.
        """
        return self.partial_update(request)


@extend_schema(
    responses={
        **data_response_dict(ContactSerializer),
        **error_response_dict(AuthenticationFailed, NotAuthenticated),
    },
)
@extend_schema_view(
    get=extend_schema(description=_('List contacts of the current user.')),
    post=extend_schema(
        description=_('Create a new contact for the current user.'),
        responses={
            **data_response_dict(
                serializer=ContactSerializer,
                status_code=status.HTTP_201_CREATED,
            ),
            **error_response_dict(AuthenticationFailed, NotAuthenticated),
        },
    ),
    put=extend_schema(
        description=_('Replace a contact selected by ID in the request body.'),
    ),
    patch=extend_schema(
        description=_('Edit a contact selected by ID in the request body.'),
    ),
)
class UserContactsView(
    GetQuerySetByAuthUserMixin,
    FilterByIdsListMixin,
    ListCreateAPIView,
    UpdateAPIView,
):
    """View for managing user contacts."""

    queryset = Contact.objects
    serializer_class = ContactSerializer
    authentication_classes = (TokenAuthentication,)
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

    @extend_schema(
        description=_('Delete selected contacts of the current user.'),
        request=ItemsSerializer,
        responses={
            status.HTTP_204_NO_CONTENT: None,
            **error_response_dict(
                MissingIdsError,
                AuthenticationFailed,
                NotAuthenticated,
            ),
        },
    )
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


@extend_schema(
    description=_('Load a shop price list from URL and update shop data.'),
    responses={
        **message_response_dict(_('Shop data updated.')),
        **error_response_dict(
            AuthenticationFailed,
            NotAuthenticated,
            YAMLParsingError,
            WebRequestConnectError,
            WebRequestResponseStatusError,
        ),
    },
)
class ShopUpdateView(APIView):
    """View for updating a shop's pricing catalog from a provided URL."""

    serializer_class = ShopUpdateURLSerializer
    authentication_classes = (TokenAuthentication,)
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        """Validate incoming URL and load shop pricing data.

        Args:
            request (Request): The request object containing shop update URL.

        Returns:
            Response: Success message after updating shop data.

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


@extend_schema(
    description=_('Return the current user shop state.'),
    responses={
        **data_response_dict(ShopSerializer),
        **error_response_dict(
            AuthenticationFailed,
            NotAuthenticated,
            PermissionDenied,
        ),
    },
)
class ShopStateView(
    GetObjectByAuthUserMixin,
    RetrieveAPIView,
    UpdateModelMixin,
):
    """View for managing a shop's active state."""

    queryset = Shop.objects
    serializer_class = ShopSerializer
    authentication_classes = (TokenAuthentication,)
    permission_classes = (IsAuthenticated, UserOwnsShop)

    @extend_schema(description=_('Modify shop active state for current user.'))
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


class BaseShopOrderView(GenericAPIView):
    """Base view for placed orders with items from certain shops."""

    queryset = PlacedOrder.objects
    serializer_class = FilteredOrderSerializer
    authentication_classes = (TokenAuthentication,)
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


@extend_schema(
    description=_("List orders with products from the current user's shop."),
    responses={
        **data_response_dict(FilteredOrderSerializer),
        **error_response_dict(
            AuthenticationFailed,
            NotAuthenticated,
            PermissionDenied,
        ),
    },
)
class ShopOrdersListView(BaseShopOrderView, ListAPIView):
    """List all placed orders containing items from the user's shop."""


@extend_schema(
    description=_("Get an order with products from the current user's shop."),
    responses={
        **data_response_dict(FilteredOrderSerializer),
        **error_response_dict(
            AuthenticationFailed,
            NotAuthenticated,
            PermissionDenied,
            NotFound(_('No orders matching this id.')),
        ),
    },
)
class ShopOrderView(BaseShopOrderView, RetrieveAPIView):
    """Show a placed order containing items from the user's shop."""


@extend_schema(
    description=_('List active shops with optional filtering.'),
    responses=data_response_dict(ShopSerializer),
)
class ShopListView(ListAPIView):
    """List view for shops with optional name filtering."""

    queryset = Shop.objects.filter(is_active=True)
    serializer_class = ShopSerializer
    filterset_class = ShopFilter


@extend_schema(
    description=_('List product categories with optional filtering.'),
    responses=data_response_dict(CategorySerializer),
)
class CategoryListView(ListAPIView):
    """List view for product categories with optional name filtering."""

    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    filterset_class = CategoryFilter


@extend_schema(
    description=_('List shop offers with optional filters.'),
    responses=data_response_dict(ShopOfferSerializer),
)
class ShopOfferListView(ListAPIView):
    """List view for shop offers with optional shop and category filtering."""

    queryset = ShopOffer.objects.select_related(
        'shop', 'product', 'product__category'
    ).filter(shop__is_active=True)
    serializer_class = ShopOfferSerializer
    filterset_class = ShopOfferFilter


@extend_schema_view(
    get=extend_schema(
        description=_('Return the current user basket.'),
        responses={
            **data_response_dict(OrderSerializer),
            **error_response_dict(
                AuthenticationFailed,
                NotAuthenticated,
                NotFound(_('Basket for this user does not exist yet.')),
            ),
        },
    ),
)
class BasketView(
    GetObjectByAuthUserMixin,
    FilterByIdsListMixin,
    RetrieveAPIView,
):
    """View for managing the user's shopping basket."""

    queryset = Basket.objects.prefetch_related('items')
    serializer_class = OrderSerializer
    authentication_classes = (TokenAuthentication,)
    permission_classes = (IsAuthenticated,)

    items_queryset = OrderItem.objects.filter(order__state=OrderState.BASKET)

    @extend_schema(
        description=_('Add items to the current user basket.'),
        responses={
            **data_response_dict(OrderSerializer),
            **error_response_dict(
                AuthenticationFailed,
                NotAuthenticated,
                MissingIdsError,
            ),
        },
    )
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

    @extend_schema(
        description=_('Update item quantities in the current user basket.'),
        responses={
            **data_response_dict(OrderSerializer),
            **error_response_dict(
                AuthenticationFailed,
                NotAuthenticated,
                MissingIdsError,
            ),
        },
    )
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

    @extend_schema(
        description=_('Delete selected items from the current user basket.'),
        request=ItemsSerializer,
        responses={
            status.HTTP_204_NO_CONTENT: None,
            **error_response_dict(
                AuthenticationFailed,
                NotAuthenticated,
                MissingIdsError,
            ),
        },
    )
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


class BaseUserOrdersView(GetQuerySetByAuthUserMixin):
    """Base view for placed orders for a user."""

    queryset = PlacedOrder.objects
    serializer_class = OrderSerializer
    authentication_classes = (TokenAuthentication,)
    permission_classes = (IsAuthenticated,)


@extend_schema_view(
    get=extend_schema(
        description=_('List orders placed by the current user.'),
        responses={
            **data_response_dict(OrderSerializer),
            **error_response_dict(AuthenticationFailed, NotAuthenticated),
        },
    )
)
class UserOrdersListView(BaseUserOrdersView, ListAPIView):
    """List orders placed by user and place new orders."""

    @extend_schema(
        description=_('Checkout the basket or reopen a canceled order.'),
        responses={
            **data_response_dict(OrderSerializer),
            **error_response_dict(
                AuthenticationFailed,
                NotAuthenticated,
                BasketCheckoutError,
                InvalidOrderStateTransitionError,
            ),
        },
    )
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


@extend_schema_view(
    get=extend_schema(
        description=_('Get an order placed by the current user.'),
        responses={
            **data_response_dict(OrderSerializer),
            **error_response_dict(
                AuthenticationFailed,
                NotAuthenticated,
                NotFound(_('Order not found.')),
            ),
        },
    ),
    delete=extend_schema(
        description=_('Cancel the selected order.'),
        responses={
            status.HTTP_204_NO_CONTENT: None,
            **error_response_dict(
                AuthenticationFailed,
                NotAuthenticated,
                NotFound(_('Order not found.')),
            ),
        },
    ),
)
class UserOrderView(BaseUserOrdersView, RetrieveDestroyAPIView):
    """Retrieve or cancel a placed order by a user."""

    @override
    def perform_destroy(self, instance: PlacedOrder) -> None:
        """Cancel the order through the state transition service.

        Args:
            instance (PlacedOrder): The order being deleted by the API.
        """
        change_order_state(instance, OrderState.CANCELLED, None, self.request)
