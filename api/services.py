from collections.abc import Callable
from collections.abc import Iterable
from dataclasses import dataclass
import functools
import json
import logging
from pathlib import Path
from typing import Any, Concatenate, Final, NamedTuple, cast, override
from urllib.parse import unquote
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.contrib.sites.shortcuts import get_current_site
from django.core.mail import send_mail
from django.db import DatabaseError
from django.db import transaction
from django.db.models import Model
from django.http import HttpRequest
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
import httpx
from rest_framework.request import Request
from rest_framework.serializers import BaseSerializer
from rest_framework.views import APIView
import yaml

from .exceptions import BasketCheckoutError
from .exceptions import BasketModifyError
from .exceptions import ErrorDict
from .exceptions import ErrorList
from .exceptions import InvalidOrderStateTransitionError
from .exceptions import LazyErrorMessage
from .exceptions import MissingIdsError
from .exceptions import NotBasketCheckoutError
from .exceptions import ShopUpdateError
from .models import Category
from .models import Contact
from .models import Order
from .models import OrderItem
from .models import OrderState
from .models import Parameter
from .models import Product
from .models import ProductParameter
from .models import Shop
from .models import ShopOffer
from .models import User
from .serializers import AddToBasketSerializer
from .serializers import EditBasketSerializer
from .serializers import EmailConfirmSerializer
from .serializers import PasswordResetConfirmSerializer
from .serializers import ShopPricingSerializer

logger = logging.getLogger(__name__)


type AnyRequest = HttpRequest | Request


def serialize(cls: type[BaseSerializer], instance: object) -> dict[str, Any]:
    """Serialize an instance using the given serializer class.

    Args:
        cls (type[BaseSerializer]): The serializer class to use.
        instance (object): The instance to serialize.

    Returns:
        dict[str, Any]: The serialized data.
    """
    serializer: BaseSerializer = cls(instance=instance)
    return cast(dict[str, Any], serializer.data)


def serialize_dict(cls: type[BaseSerializer], **kwargs: Any) -> dict[str, Any]:
    """Serialize keyword arguments using the given serializer class.

    Args:
        cls (type[BaseSerializer]): The serializer class to use.
        kwargs: Keyword arguments to serialize.

    Returns:
        dict[str, Any]: The serialized data.
    """
    return serialize(cls, kwargs)


def validate_view(
    cls: type[BaseSerializer],
    view: APIView,
    /,
    raise_exception: bool = True,
    **kwargs: object,
) -> dict[str, Any]:
    """Validate serializer data from a view request.

    Args:
        cls (type[BaseSerializer]): The serializer class to use.
        view (APIView): The view containing the request.
        raise_exception (bool): Whether to raise exception on invalid data.
        kwargs (object): Fields for the serializer context.

    Returns:
        dict[str, Any]: The validated data.
    """
    request = cast(Request, view.request)
    return validate_request(
        cls,
        request,
        raise_exception=raise_exception,
        **kwargs,
    )


def validate_request(
    cls: type[BaseSerializer],
    request: Request,
    /,
    raise_exception: bool = True,
    **kwargs: object,
) -> dict[str, Any]:
    """Validate serializer data from a DRF request object.

    Args:
        cls (type[BaseSerializer]): The serializer class to use.
        request (Request): The DRF request containing the data.
        raise_exception (bool): Whether to raise on invalid data.
        kwargs (object): Fields for the serializer context.

    Returns:
        dict[str, Any]: The validated serializer data.
    """
    kwargs['user'] = request.user
    data = cast(dict[str, Any], request.data)
    return validate_data(cls, data, raise_exception=raise_exception, **kwargs)


def validate_data(
    cls: type[BaseSerializer],
    data: object,
    /,
    raise_exception: bool = True,
    **kwargs: object,
) -> dict[str, Any]:
    """Validate data using the given serializer class.

    Args:
        cls (type[BaseSerializer]): The serializer class to use.
        data (object): The data to validate.
        raise_exception (bool): Whether to raise exception on invalid data.
        kwargs (object): Fields for the serializer context.

    Returns:
        dict[str, Any]: The validated data.
    """
    serializer: BaseSerializer = cls(data=data, context=kwargs)
    serializer.is_valid(raise_exception=raise_exception)
    return get_validated_data(serializer)


def get_validated_data(serializer: BaseSerializer) -> dict[str, Any]:
    """Extract validated data from a serializer.

    Args:
        serializer (BaseSerializer): The serializer instance.

    Returns:
        dict[str, Any]: The validated data.
    """
    return cast(dict[str, Any], serializer.validated_data)


@functools.cache
def get_model_fields(cls: type[Model]) -> set[str]:
    """Return a set of field names defined on a Django model class.

    Args:
        cls (type[Model]): The Django model class.

    Returns:
        set[str]: Set of field names from the model.
    """
    return {field.name for field in cls._meta.fields}


def filter_by_fields(
    cls: type[Model],
    data: dict[str, object],
) -> dict[str, object]:
    """Filter data keys that are model field names.

    Args:
        cls (type[Model]): The Django model class.
        data (dict[str, object]): Dictionary of data to filter.

    Returns:
        dict[str, object]: Filtered dictionary with valid model field keys.
    """
    fields = get_model_fields(cls)
    return {field: value for field, value in data.items() if field in fields}


def get_model[T: Model](cls: type[T], **kwargs: object) -> T:
    """Retrieve a single model instance by the given lookup parameters.

    Args:
        cls (type[T]): The Django model class.
        kwargs (object): Keyword arguments for model field lookup.

    Returns:
        T: The retrieved model instance.

    Raises:
        T.DoesNotExist: If no matching instance is found.
    """
    kwargs = filter_by_fields(cls, kwargs)
    return cls.objects.get(**kwargs)


def locate_model_items[T: Model](
    cls: type[T],
    items: Iterable[dict[str, Any]],
    _item_id_field: str = 'id',
    _model_id_field: str = 'id',
    **kwargs: object,
) -> dict[int, T]:
    """Locate multiple model instances from an iterable of item dictionaries.

    Retrieves model instances by extracting IDs from item dictionaries and
    looking them up using the specified ID fields. Raises an error if any
    requested items are not found.

    Args:
        cls (type[T]): The Django model class.
        items (Iterable[dict[str, Any]]): List of item dictionaries.
        _item_id_field (str): Field name in item dictionary for the ID.
        _model_id_field (str): Field name on the model for lookup.
        kwargs (object): Additional filter conditions for the model lookup.

    Returns:
        dict[int, T]: Dictionary mapping item IDs to model instances.

    Raises:
        MissingIdsError: If any requested IDs are not found in the database.
    """
    model_items: dict[int, T] = {}
    missing_ids = set[int]()
    kwargs = filter_by_fields(cls, kwargs)
    for item in items:
        try:
            item_id = item[_item_id_field]
        except KeyError:
            # Failed to extract the key, just skip this record
            continue
        try:
            lookup = {_model_id_field: item_id} | kwargs
            model_item = cls.objects.get(**lookup)
        except cls.DoesNotExist:
            missing_ids.add(item_id)
        else:
            model_items[item_id] = model_item

    if missing_ids:
        raise MissingIdsError(missing_ids)
    return model_items


def create_model[T: Model](
    cls: type[T],
    data: dict[str, object] | None = None,
    **kwargs: object,
) -> T:
    """Create a model instance using data filtered to model fields.

    Args:
        cls (type[T]): The Django model class.
        data (dict[str, object] | None): Data to use for creation.
        kwargs (object): Additional model field values.

    Returns:
        T: The created model instance.
    """
    data = data or {}
    data |= kwargs
    data = filter_by_fields(cls, data)
    return cls.objects.create(**data)


def get_or_create_model[T: Model](
    cls: type[T],
    defaults: dict[str, object] | None = None,
    **kwargs: object,
) -> T:
    """Get a model instance or create a new one if not exists.

    Args:
        cls (type[T]): The Django model class.
        defaults (dict[str, object] | None): Default values for creation.
        kwargs (object): Lookup fields for existing model instance.

    Returns:
        T: The retrieved or newly created model instance.
    """
    defaults = defaults and filter_by_fields(cls, defaults)
    kwargs = filter_by_fields(cls, kwargs)
    item, _ = cls.objects.get_or_create(defaults=defaults, **kwargs)
    return item


class TokenGenerator(PasswordResetTokenGenerator):
    """Custom token generator for one-time validation codes."""

    def __init__(self, salt: str | None = None) -> None:
        """Initialize the token generator with an optional salt.

        Args:
            salt (str | None): Optional salt string to use for token
                generation. If provided, overrides the default `key_salt`.
        """
        super().__init__()
        if salt is not None:
            self.key_salt = salt

    @override
    def _make_hash_value(self, user: AbstractBaseUser, timestamp: int) -> str:
        """Return a hash value for the one-time validation token.

        Includes the user's active state to the hash so the token
        is invalidated if `user.is_active` changes.

        Args:
            user (AbstractBaseUser): The user for whom the token is generated.
            timestamp (int): The token timestamp.

        Returns:
            A hash string used for token validation.
        """
        result = super()._make_hash_value(user, timestamp)
        return f'{result}{user.is_active}'


email_verify_token_gen = TokenGenerator('email-verify')
password_reset_token_gen = TokenGenerator('password-reset')


def check_email_verify_token(user: User | None, token: str | None) -> bool:
    """Check if the email verification token is valid for the user.

    Args:
        user (User | None): The user to validate against.
        token (str | None): The token to check.

    Returns:
        bool: True if token is valid, False otherwise.
    """
    return email_verify_token_gen.check_token(user, token)


def check_password_reset_token(user: User | None, token: str | None) -> bool:
    """Check if the password reset token is valid for the user.

    Args:
        user (User | None): The user instance to validate.
        token (str | None): The token string to check.

    Returns:
        bool: True if the token is valid for the given user.
    """
    return password_reset_token_gen.check_token(user, token)


@dataclass(frozen=True, slots=True)
class EmailTemplateSet:
    """Template paths used to render one email message."""

    subject: str
    text: str
    html: str | None = None


def get_request_context(request: AnyRequest) -> dict[str, Any]:
    """Build the base context used for email message templates.

    Args:
        request (AnyRequest): The request object.

    Returns:
        dict[str, Any]: Context dictionary for the template.
    """
    if isinstance(request, Request):
        # `Request` works as a proxy over `HttpRequest`
        request = cast(HttpRequest, request)
    current_site = get_current_site(request)
    site_name = current_site.name
    domain = current_site.domain
    use_https = request.is_secure()
    return {
        'domain': domain,
        'site_name': site_name,
        'protocol': 'https' if use_https else 'http',
    }


def format_request_data(
    data: object,
    serializer: type[BaseSerializer],
) -> str:
    """Format serializer data as pretty-printed JSON for email templates.

    Args:
        data (object): The raw data to validate and serialize.
        serializer (type[BaseSerializer]): The serializer class for `data`.

    Returns:
        str: The serialized JSON string.
    """
    request_data = serialize(serializer, data)
    return json.dumps(request_data, indent=4)


def get_verify_context(
    request: AnyRequest,
    view_name: str,
    request_type: str,
    request_data: object,
    serializer_cls: type[BaseSerializer],
) -> dict[str, Any]:
    """Build email context for token verification requests.

    Args:
        request (AnyRequest): The request used to build absolute URLs.
        view_name (str): URL name for the verification endpoint.
        request_type (str): HTTP method shown in the email.
        request_data (object): Payload included in the email instructions.
        serializer_cls (type[BaseSerializer]): Serializer for the payload.

    Returns:
        dict[str, Any]: Context data for verification email templates.
    """
    path = reverse(view_name)
    request_url = request.build_absolute_uri(path)
    request_data = format_request_data(request_data, serializer_cls)
    context = get_request_context(request)
    return context | {
        'request_type': request_type,
        'request_url': request_url,
        'request_data': request_data,
    }


EMAIL_VERIFICATION_TEMPLATES: Final = EmailTemplateSet(
    subject='api/email_verification_subject.txt',
    text='api/email_verification_email.txt',
    html='api/email_verification_email.html',
)


def send_email_verification_mail(
    request: AnyRequest,
    user: User | None,
    email: str | None = None,
    from_email: str | None = None,
) -> str | None:
    """Send email verification mail to user.

    Args:
        request (AnyRequest): The request object.
        user (User | None): The user to send mail to.
        email (str | None): The email address.
        from_email (str | None): From email address.

    Returns:
        str | None: Email confirmation token generated if any.
    """
    if user is None:
        logger.info('User %s does not exist', email)
        return None
    if user.is_active:
        logger.info('User %s already confirmed', user.email)
        return None

    templates = EMAIL_VERIFICATION_TEMPLATES
    email = cast(str, user.email)
    token = email_verify_token_gen.make_token(user)
    context = get_verify_context(
        request=request,
        view_name='email-confirm',
        request_type='POST',
        request_data={'email': email, 'token': token},
        serializer_cls=EmailConfirmSerializer,
    )
    context['token'] = token

    render_and_send_mail(templates, context, email, from_email)
    return token


PASSWORD_RESET_TEMPLATES: Final = EmailTemplateSet(
    subject='api/password_reset_subject.txt',
    text='api/password_reset_email.txt',
    html='api/password_reset_email.html',
)


def send_password_reset_mail(
    request: AnyRequest,
    user: User | None,
    email: str | None = None,
    from_email: str | None = None,
) -> str | None:
    """Send a password reset email to the given user.

    Args:
        request (AnyRequest): The request object.
        user (User | None): The user who will receive the reset email.
        email (str | None): Optional override email address.
        from_email (str | None): Optional from-address for the email.

    Returns:
        str | None: Password reset token generated if any.
    """
    if user is None:
        logger.info('User %s does not exist', email)
        return None
    if not user.is_active:
        logger.info('User %s is inactive', user.email)
        return None

    templates = PASSWORD_RESET_TEMPLATES
    email = cast(str, user.email)
    token = password_reset_token_gen.make_token(user)
    context = get_verify_context(
        request=request,
        view_name='password-reset-confirm',
        request_type='POST',
        request_data={
            'email': email,
            'password': 'your_new_password',
            'token': token,
        },
        serializer_cls=PasswordResetConfirmSerializer,
    )
    context['token'] = token

    render_and_send_mail(templates, context, email, from_email)
    return token


def notify_order_state_mail(
    request: AnyRequest,
    order: Order,
    from_email: str | None = None,
) -> None:
    """Send all emails required by the current order state.

    Args:
        request (AnyRequest): The request used to build email links.
        order (Order): The order whose state should be announced.
        from_email (str | None): Optional sender email address.
    """
    notify_order_state_user_mail(request, order, from_email)
    notify_order_state_shop_mail(request, order, from_email)


def notify_order_state_on_commit(
    request: AnyRequest,
    order_id: object,
) -> None:
    """Schedule order state notifications after transaction commit.

    Args:
        request (AnyRequest): The request used to build email links.
        order_id (object): Primary key of the order to notify about.
    """

    def notify_callback() -> None:
        """Reload the order and send state notifications."""
        order = Order.objects.get(pk=order_id)
        notify_order_state_mail(request, order)

    transaction.on_commit(notify_callback)


def get_order_context(
    request: AnyRequest,
    order: Order,
    view_name: str,
) -> dict[str, Any]:
    """Build email context shared by order notification templates.

    Args:
        request (AnyRequest): The request used to build the order URL.
        order (Order): The order included in the email context.
        view_name (str): URL name for the order detail endpoint.

    Returns:
        dict[str, Any]: Context data for order email templates.
    """
    path = reverse(view_name, kwargs={'pk': order.pk})
    order_url = request.build_absolute_uri(path)
    context = get_request_context(request)
    return context | {
        'order_id': order.pk,
        'order_state': OrderState(order.state).label,
        'order_url': order_url,
    }


ORDER_CREATED_TEMPLATES: Final = EmailTemplateSet(
    subject='api/order_created_subject.txt',
    text='api/order_created_email.txt',
    html='api/order_created_email.html',
)


ORDER_CANCELLED_TEMPLATES: Final = EmailTemplateSet(
    subject='api/order_cancelled_subject.txt',
    text='api/order_cancelled_email.txt',
    html='api/order_cancelled_email.html',
)


ORDER_STATE_CHANGE_TEMPLATES: Final = EmailTemplateSet(
    subject='api/order_state_change_subject.txt',
    text='api/order_state_change_email.txt',
    html='api/order_state_change_email.html',
)


@functools.cache
def get_notify_user_templates(state: OrderState) -> EmailTemplateSet | None:
    """Return user notification templates for the order state.

    Args:
        state (OrderState): The current order state.

    Returns:
        EmailTemplateSet | None: Matching templates, or None when no
            user notification is needed.
    """
    if state == OrderState.NEW:
        return ORDER_CREATED_TEMPLATES
    if state == OrderState.CANCELLED:
        return ORDER_CANCELLED_TEMPLATES
    if state in OrderState.active():
        return ORDER_STATE_CHANGE_TEMPLATES
    return None


def notify_order_state_user_mail(
    request: AnyRequest,
    order: Order,
    from_email: str | None = None,
) -> None:
    """Send an order state notification to the order owner.

    Args:
        request (AnyRequest): The request used to build email links.
        order (Order): The order whose owner should be notified.
        from_email (str | None): Optional sender email address.
    """
    templates = get_notify_user_templates(order.state)
    if templates is None:
        # No need to notify the user
        return

    user = order.user
    email = cast(str, user.email)
    context = get_order_context(request, order, 'order')
    render_and_send_mail(templates, context, email, from_email)


ORDER_PLACED_SHOP_ADMIN_TEMPLATES: Final = EmailTemplateSet(
    subject='api/order_placed_shop_admin_subject.txt',
    text='api/order_placed_shop_admin_email.txt',
    html='api/order_placed_shop_admin_email.html',
)


@functools.cache
def get_notify_shop_templates(state: OrderState) -> EmailTemplateSet | None:
    """Return shop admin notification templates for the order state.

    Args:
        state (OrderState): The current order state.

    Returns:
        EmailTemplateSet | None: Matching templates, or None when shop
            admins do not need a notification.
    """
    if state == OrderState.NEW:
        return ORDER_PLACED_SHOP_ADMIN_TEMPLATES
    return None


def get_shop_context(
    order: Order,
    shop: Shop,
    base_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build email context for one shop's items in an order.

    Args:
        order (Order): The order containing shop items.
        shop (Shop): The shop whose line items should be included.
        base_context (dict[str, Any] | None): Shared email context.

    Returns:
        dict[str, Any]: Context data for the shop admin email.
    """
    items = list(
        OrderItem.objects.filter(
            order=order,
            shop_offer__shop=shop,
        )
        .select_related('shop_offer__product')
        .order_by('pk')
    )
    total_sum = sum(x.sum for x in items)
    base_context = base_context or {}
    return base_context | {
        'shop_name': shop.name,
        'items': items,
        'total_sum': total_sum,
    }


def notify_order_state_shop_mail(
    request: AnyRequest,
    order: Order,
    from_email: str | None = None,
) -> None:
    """Send order notifications to affected shop admins.

    Args:
        request (AnyRequest): The request used to build email links.
        order (Order): The order whose shops should be notified.
        from_email (str | None): Optional sender email address.
    """
    templates = get_notify_shop_templates(order.state)
    if templates is None:
        # No need to notify any admins
        return

    base_context = get_order_context(request, order, 'order')
    shops = (
        Shop.objects.filter(offers__order_items__order_id=order.pk)
        .distinct()
        .select_related('user')
        .all()
    )

    for shop in shops:
        admin: User = shop.user
        email = cast(str, admin.email)
        context = get_shop_context(order, shop, base_context)
        render_and_send_mail(templates, context, email, from_email)


def render_and_send_mail(
    templates: EmailTemplateSet,
    context: dict[str, Any],
    to_email: str,
    from_email: str | None = None,
) -> None:
    """Send a django.core.mail.EmailMultiAlternatives to `to_email`.

    Args:
        templates (EmailTemplateSet): Templates for email message rendering.
        context (dict[str, Any]): Template context data.
        to_email (str): Recipient email address.
        from_email (str | None): Optional sender email address.
    """
    context['email'] = to_email
    subject = render_to_string(templates.subject, context)
    # Email subject *must not* contain newlines
    subject = ''.join(subject.splitlines())

    text = render_to_string(templates.text, context)
    html = templates.html and render_to_string(templates.html, context)

    try:
        send_mail(
            subject=subject,
            message=text,
            from_email=from_email,
            recipient_list=[to_email],
            html_message=html,
        )
    except Exception:
        logger.exception('Failed to send email to user %s', to_email)


def debug_process_file_url[**P](
    func: Callable[Concatenate[str, P], httpx.Response],
) -> Callable[Concatenate[str, P], httpx.Response]:
    """Decorator allowing local file URL processing in DEBUG mode only.

    When `DEBUG` is True, this decorator enables fetching local
    files via file:// URLs. In production, file URLs are handled
    by the original function.

    Args:
        func (Callable): The function to decorate, accepting URL as
            its first parameter.

    Returns:
        Callable: The decorated function if DEBUG is True, otherwise
            the original function.
    """
    if not settings.DEBUG:
        # No wrapping
        return func

    @functools.wraps(func)
    def wrapper(url: str, *args: Any, **kwargs: Any) -> httpx.Response:
        """Process URL, adding support for file:// scheme.

        Args:
            url (str): The URL to process (http://, https://, or file://).
            args: Additional positional arguments for the decorated function.
            kwargs: Additional keyword arguments for the decorated function.

        Returns:
            httpx.Response: HTTP response object.
        """
        parts = urlparse(url)
        if parts.scheme != 'file':
            return func(url, *args, **kwargs)

        path = unquote(parts.path)

        # Convert Windows absolute paths with drive letter
        if path.startswith('/') and len(path) >= 3 and path[2] == ':':
            path = path[1:]

        path = Path(path)
        try:
            content = path.read_bytes()
        except FileNotFoundError:
            return httpx.Response(404, text='File not found')
        except OSError as exc:
            return httpx.Response(500, text=str(exc))
        return httpx.Response(
            200,
            content=content,
            headers={'content-length': str(len(content))},
        )

    return wrapper


@debug_process_file_url
def retry_get_url(url: str, retries: int = 10) -> httpx.Response:
    """Retry an HTTP GET request no more than `retries` times.

    Args:
        url (str): The URL to request.
        retries (int): Number of retry attempts before failing.

    Returns:
        httpx.Response: The successful HTTP response.
    """
    with httpx.Client() as session:
        fail_count = 0
        while True:
            try:
                response = session.get(url)
            except httpx.RequestError:
                fail_count += 1
                if fail_count >= retries:
                    raise
            else:
                return response


def update_shop_pricing_yaml(user: User, url: str, content: str):
    """Update shop pricing from YAML document.

    Args:
        user (User): The shop owner.
        url (str): The pricing document URL.
        content (str): The YAML document.
    """
    data = yaml.safe_load(content)
    update_shop_pricing(user, url, data)


def update_shop_pricing(user: User, url: str, data: dict[str, Any]) -> None:
    """Apply shop pricing from processed input data.

    Args:
        user (User): The shop owner.
        url (str): Pricing document URL.
        data (dict[str, Any]): Parsed pricing data.
    """
    data = validate_data(ShopPricingSerializer, data)
    try:
        _update_shop_pricing_impl(user, url, data)
    except DatabaseError as e:
        logger.exception('Shop update error: %s', url)
        raise ShopUpdateError from e


@transaction.atomic
def _update_shop_pricing_impl(
    user: User,
    url: str,
    data: dict[str, Any],
) -> None:
    """Apply shop pricing from validated data.

    Args:
        user (User): The shop owner.
        url (str): Pricing document URL.
        data (dict[str, Any]): Validated shop pricing payload.
    """
    shop = get_or_create_model(Shop, data, name=data['shop'], user=user)
    shop.url = url
    shop.save()

    # Use category IDs from document for in-document mapping only
    categories = {
        item['id']: get_or_create_model(Category, name=item['name'])
        for item in data['categories']
    }

    # Clear all shop offers but reuse product records
    shop.offers.all().delete()

    for item in data['goods']:
        item['category'] = categories[item['category']]
        product = get_or_create_model(Product, item, name=item['name'])
        offer = create_model(ShopOffer, item, product=product, shop=shop)

        for name, value in item['parameters'].items():
            parameter = get_or_create_model(Parameter, name=name)
            create_model(
                ProductParameter,
                parameter=parameter,
                offer=offer,
                value=value,
            )


def add_to_basket(user: User, request: Request) -> None:
    """Add items to the user's shopping basket from request data.

    Validates the request data and adds shop offers to the user's basket
    (creates or retrieves basket order). If an item is already in the basket,
    its quantity is increased.

    Args:
        user (User): The user adding items to their basket.
        request (Request): The request object containing basket items.

    Raises:
        BasketModifyError: If there's a database error during the operation.
    """
    data = validate_request(AddToBasketSerializer, request)
    try:
        _add_to_basket_impl(user, data)
    except DatabaseError as e:
        logger.exception('Add to basket error')
        raise BasketModifyError from e


@transaction.atomic
def _add_to_basket_impl(user: User, data: dict[str, Any]) -> None:
    """Add validated items to the user's basket order.

    Creates a new basket order if needed and adds shop offer items to it.
    If an item is already in the basket, increases its quantity instead
    of creating a duplicate.

    Args:
        user (User): The user who owns the basket.
        data (dict[str, Any]): Validated data containing items to add.
    """
    basket = get_or_create_model(Order, user=user, state=OrderState.BASKET)
    offers = locate_model_items(ShopOffer, data['items'], 'shop_offer_id')

    for item in data['items']:
        offer = offers[item['shop_offer_id']]
        try:
            order_item = get_model(OrderItem, order=basket, shop_offer=offer)
        except OrderItem.DoesNotExist:
            create_model(OrderItem, item, shop_offer=offer, order=basket)
        else:
            # If item already in the basket, just increase its quantity
            order_item.quantity += item['quantity']
            order_item.save()


def edit_basket(user: User, request: Request) -> None:
    """Update quantities of items in the user's shopping basket.

    Validates the request data and updates order item quantities in the
    user's basket based on the provided item data.

    Args:
        user (User): The user updating their basket.
        request (Request): The request object containing updated items.

    Raises:
        BasketModifyError: If there's a database error during the operation.
    """
    data = validate_request(EditBasketSerializer, request)
    try:
        _edit_basket_impl(user, data)
    except DatabaseError as e:
        logger.exception('Edit basket error')
        raise BasketModifyError from e


@transaction.atomic
def _edit_basket_impl(user: User, data: dict[str, Any]) -> None:
    """Update quantities for items in the user's basket order.

    Modifies the quantity of existing order items in the user's basket
    based on the provided item data.

    Args:
        user (User): The user whose basket is being updated.
        data (dict[str, Any]): Validated data with new quantities.
    """
    basket = get_or_create_model(Order, user=user, state=OrderState.BASKET)
    order_items = locate_model_items(OrderItem, data['items'], order=basket)

    for item in data['items']:
        order_item = order_items[item['id']]
        order_item.quantity = item['quantity']
        order_item.save()


def get_order_state(order_id: object) -> OrderState:
    """Return the persisted state for an order ID.

    Args:
        order_id (object): The order primary key.

    Returns:
        OrderState: The order state stored in the database.
    """
    return Order.objects.only('state').get(pk=order_id).state


def is_order_active(order_id: object) -> bool:
    """Return whether an order ID refers to an active order.

    Args:
        order_id (object): The order primary key, or None.

    Returns:
        bool: True when the order is active.
    """
    if order_id is None:
        return False
    state = get_order_state(order_id)
    return state in OrderState.active()


type OrderItems = Iterable[OrderItem]
type ShopOfferDict = dict[object, ShopOffer]


class OrderData(NamedTuple):
    """Locked order data used for stock-sensitive operations."""

    order: Order
    items: OrderItems
    offers: ShopOfferDict


def _lock_order_items(order: Order) -> OrderData:
    """Lock an order with its items and related offers.

    Args:
        order (Order): The order to lock.

    Returns:
        OrderData: Locked order, items, and shop offers.
    """
    # Lock the parent order object
    order = Order.objects.select_for_update().get(pk=order.pk)
    items = list(OrderItem.objects.filter(order_id=order.pk))

    # Lock all the shop offers
    offer_ids = {item.shop_offer_id for item in items}
    offers = {
        offer.pk: offer
        for offer in (
            ShopOffer.objects.select_for_update().filter(pk__in=offer_ids)
        )
    }
    return OrderData(order, items, offers)


def _validate_basket_items(items: OrderItems, offers: ShopOfferDict) -> None:
    """Validate basket items against active shops and available stock.

    Args:
        items (OrderItems): Basket items to validate.
        offers (ShopOfferDict): Shop offers keyed by primary key.

    Raises:
        BasketCheckoutError: If any item cannot be checked out.
    """
    errors = ErrorDict()

    for item in items:
        offer = offers[item.shop_offer_id]
        item_errors = ErrorList()

        if not offer.is_active:
            item_errors.append(
                LazyErrorMessage(
                    _('Item {item}: Shop offer {offer} is inactive.'),
                    item=item.pk,
                    offer=offer.pk,
                )
            )

        if item.quantity > offer.quantity:
            item_errors.append(
                LazyErrorMessage(
                    _(
                        'Item {item}: Quantity {value} exceeds '
                        'the maximum of {max} available.'
                    ),
                    item=item.pk,
                    value=item.quantity,
                    max=offer.quantity,
                )
            )

        if item_errors:
            errors['items'] += item_errors

    if errors:
        raise BasketCheckoutError(errors)


def _reserve_stock(items: OrderItems, offers: ShopOfferDict) -> None:
    """Decrease stock quantities for order items.

    Args:
        items (OrderItems): Order items reserving stock.
        offers (ShopOfferDict): Shop offers keyed by primary key.
    """
    update_offers: list[ShopOffer] = []
    for item in items:
        offer = offers[item.shop_offer_id]
        offer.quantity -= item.quantity
        update_offers.append(offer)
    ShopOffer.objects.bulk_update(update_offers, ['quantity'])


def _replenish_stock(items: OrderItems, offers: ShopOfferDict) -> None:
    """Restore stock quantities for order items.

    Args:
        items (OrderItems): Order items returning stock.
        offers (ShopOfferDict): Shop offers keyed by primary key.
    """
    update_offers: list[ShopOffer] = []
    for item in items:
        offer = offers[item.shop_offer_id]
        offer.quantity += item.quantity
        update_offers.append(offer)
    ShopOffer.objects.bulk_update(update_offers, ['quantity'])


@transaction.atomic
def checkout_basket(
    basket: Order,
    contact: Contact,
    notify_request: AnyRequest | None = None,
) -> None:
    """Perform basket checkout by validating and converting a basket order.

    This function locks the basket and related shop offers, validates that
    all requested quantities are available, and then converts the basket to a
    placed order while deducting inventory quantities.

    Args:
        basket (Order): The basket order to checkout.
        contact (Contact): The contact information for the order.
        notify_request (AnyRequest | None): Request used for notifications.
            If None then no notifications are performed.

    Raises:
        NotBasketCheckoutError: If the provided order is not a basket.
        BasketCheckoutError: Unable to checkout the provided basket.
    """
    if basket.state != OrderState.BASKET:
        raise NotBasketCheckoutError

    basket, items, offers = _lock_order_items(basket)
    _validate_basket_items(items, offers)

    order = create_model(
        Order,
        user=basket.user,
        contact=contact,
        state=OrderState.NEW,
    )

    _reserve_stock(items, offers)

    # Move basket items to the created order
    for item in items:
        item.order_id = order.pk
    OrderItem.objects.bulk_update(items, ['order_id'])

    if notify_request is not None:
        notify_order_state_on_commit(notify_request, order.pk)


@transaction.atomic
def change_order_state(
    order: Order,
    new_state: OrderState,
    notify_request: AnyRequest | None = None,
) -> None:
    """Apply an allowed order state transition and update stock.

    Cancelling an order replenishes reserved stock. Reopening a cancelled
    order to the new state reserves stock again.

    Args:
        order (Order): The order to update.
        new_state (OrderState): The requested target state.
        notify_request (AnyRequest | None): Request used for notifications.
            If None then no notifications are performed.

    Raises:
        InvalidOrderStateTransitionError: If the transition is not allowed.
    """
    old_state: OrderState = order.state
    validate_order_state_transition(old_state, new_state)
    order, items, offers = _lock_order_items(order)

    # Update shop available stock
    if new_state == OrderState.CANCELLED:
        _replenish_stock(items, offers)
    elif new_state == OrderState.NEW and old_state == OrderState.CANCELLED:
        _reserve_stock(items, offers)

    order.state = new_state
    order.save()

    if notify_request is not None:
        notify_order_state_on_commit(notify_request, order.pk)


_ALLOWED_ORDER_STATE_TRANSITIONS: Final[dict[OrderState, set[OrderState]]] = {
    OrderState.CANCELLED: {OrderState.NEW},
    OrderState.BASKET: set(),
    OrderState.NEW: {OrderState.CONFIRMED, OrderState.CANCELLED},
    OrderState.CONFIRMED: {OrderState.ASSEMBLED, OrderState.CANCELLED},
    OrderState.ASSEMBLED: {OrderState.SENT, OrderState.CANCELLED},
    OrderState.SENT: {OrderState.COMPLETED, OrderState.CANCELLED},
    OrderState.COMPLETED: set(),
}


def get_allowed_state_transitions(state: OrderState) -> set[OrderState]:
    """Return order states reachable from the given state.

    Args:
        state (OrderState): The current order state.

    Returns:
        set[OrderState]: The current state plus allowed target states.

    Raises:
        NotImplementedError: If the state is not configured.
    """
    try:
        allowed = _ALLOWED_ORDER_STATE_TRANSITIONS[state]
    except KeyError:
        raise NotImplementedError
    return {state} | allowed


def validate_order_state_transition(old: OrderState, new: OrderState) -> None:
    """Validate a requested order state change.

    Args:
        old (OrderState): The current order state.
        new (OrderState): The requested order state.

    Raises:
        InvalidOrderStateTransitionError: If the transition is not allowed.
    """
    allowed = get_allowed_state_transitions(old)
    if new not in allowed:
        raise InvalidOrderStateTransitionError(old, new)
