from collections import defaultdict
from collections.abc import Callable
from collections.abc import Iterable
from collections.abc import Mapping
import functools
import json
import logging
from pathlib import Path
from typing import (
    Any,
    Concatenate,
    Final,
    NamedTuple,
    cast,
    overload,
    override,
)
from urllib.parse import unquote
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.db import transaction
from django.db.models import Model
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
import httpx
from rest_framework.request import Request
from rest_framework.serializers import BaseSerializer
from rest_framework.views import APIView
import yaml

from .exceptions import BasketCheckoutError
from .exceptions import ErrorDict
from .exceptions import ErrorList
from .exceptions import InvalidOrderStateTransitionError
from .exceptions import LazyErrorMessage
from .exceptions import MissingIdsError
from .exceptions import NotBasketCheckoutError
from .exceptions import WebRequestConnectError
from .exceptions import WebRequestError
from .exceptions import WebRequestResponseStatusError
from .exceptions import WebRequestTimeoutError
from .exceptions import WebRequestTooManyRedirectsError
from .exceptions import YAMLParsingError
from .models import Basket
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
from .models import retry_transaction
from .serializers import EmailConfirmSerializer
from .serializers import PasswordResetConfirmSerializer
from .serializers import ShopPricingSerializer
from .tasks import notify_order_state
from .tasks import send_password_reset_mail
from .tasks import send_user_verification_mail
from .templates import AnyRequest
from .templates import get_order_context
from .templates import get_verify_context

logger = logging.getLogger(__name__)


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
        **kwargs (Any): Keyword arguments to serialize.

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
        **kwargs (object): Fields for the serializer context.

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
        **kwargs (object): Fields for the serializer context.

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
        **kwargs (object): Fields for the serializer context.

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


def filter_by_fields[T](
    cls: type[Model],
    data: dict[str, T],
) -> dict[str, T]:
    """Filter data keys that are model field names.

    Args:
        cls (type[Model]): The Django model class.
        data (dict[str, T]): Dictionary of data to filter.

    Returns:
        dict[str, T]: Filtered dictionary with valid model field keys.
    """
    fields = get_model_fields(cls)
    return {field: value for field, value in data.items() if field in fields}


def model_exists[T: Model](cls: type[T], **kwargs: object) -> bool:
    """Return whether a model exists for the given lookup fields.

    Args:
        cls (type[T]): The Django model class.
        **kwargs (object): Lookup fields for the model query.

    Returns:
        bool: True when a matching model exists.
    """
    kwargs = filter_by_fields(cls, kwargs)
    return cls.objects.filter(**kwargs).exists()


def get_model[T: Model](cls: type[T], **kwargs: object) -> T:
    """Retrieve a single model instance by the given lookup parameters.

    Args:
        cls (type[T]): The Django model class.
        **kwargs (object): Keyword arguments for model field lookup.

    Returns:
        T: The retrieved model instance.

    Raises:
        T.DoesNotExist: If no matching instance is found.
    """
    kwargs = filter_by_fields(cls, kwargs)
    return cls.objects.get(**kwargs)


def get_and_lock_model[T: Model](cls: type[T], **kwargs: object) -> T:
    """Retrieve and lock a model instance for update.

    Args:
        cls (type[T]): The Django model class.
        **kwargs (object): Lookup fields for the model query.

    Returns:
        T: The locked model instance.
    """
    kwargs = filter_by_fields(cls, kwargs)
    return cls.objects.select_for_update().order_by('id').get(**kwargs)


def lock_model_instance(instance: Model) -> None:
    """Lock an existing model instance by primary key.

    Args:
        instance (Model): The model instance to lock.
    """
    cls = instance._meta.model  # noqa: SLF001
    cls.objects.select_for_update().only('pk').order_by('id').get(
        pk=instance.pk
    )


type ModelKey[T] = T | tuple[T, ...]


@overload
def model_dict_key[T](item: Mapping[str, T], key_field: str, /) -> T: ...


@overload
def model_dict_key[T](
    item: Mapping[str, T],
    key_field1: str,
    key_field2: str,
    /,
    *key_fields: str,
) -> tuple[T, ...]: ...


def model_dict_key[T](
    item: Mapping[str, T],
    *key_fields: str,
) -> ModelKey[T]:
    """Build a lookup key from dictionary fields.

    Args:
        item (Mapping[str, T]): Mapping containing key fields.
        *key_fields (str): Field names to include in the key.

    Returns:
        ModelKey[T]: Empty tuple, single value, or tuple of values.
    """
    if len(key_fields) == 1:
        return item[key_fields[0]]
    return tuple(map(item.__getitem__, key_fields))


@overload
def model_object_key(obj: object, key_field: str, /) -> object: ...


@overload
def model_object_key(
    obj: object,
    key_field1: str,
    key_field2: str,
    /,
    *key_fields: str,
) -> tuple[object, ...]: ...


def model_object_key(obj: object, *key_fields: str) -> ModelKey[object]:
    """Build a lookup key from object attributes.

    Args:
        obj (object): Object containing key attributes.
        *key_fields (str): Attribute names to include in the key.

    Returns:
        ModelKey[object]: Empty tuple, single value, or tuple of values.
    """
    if len(key_fields) == 1:
        return getattr(obj, key_fields[0])
    return tuple(getattr(obj, key_field) for key_field in key_fields)


@transaction.atomic
def get_or_create_models_by_field[T: Model](
    cls: type[T],
    data: Iterable[dict[str, Any]],
    *key_fields: str,
) -> list[T]:
    """Get or create multiple models using shared key fields.

    Args:
        cls (type[T]): The Django model class.
        data (Iterable[dict[str, Any]]): Model data dictionaries.
        *key_fields (str): Field names used to identify existing rows.

    Returns:
        list[T]: Existing and newly created model instances.
    """
    keys = {model_dict_key(item, *key_fields) for item in data}
    if len(key_fields) == 1:
        # WHERE field IN (values, ...)
        query = Q(**{f'{key_fields[0]}__in': keys})
    elif keys:
        # WHERE fields = values1 OR fields = values2 OR ...
        query = Q()
        for key in keys:
            query |= Q(**dict(zip(key_fields, key)))
    else:
        # WHERE id IN ()
        query = Q(pk__in={})

    existing = list(
        cls.objects.select_for_update().filter(query).order_by('id')
    )
    existing_keys = {model_object_key(obj, *key_fields) for obj in existing}

    # Exclude duplicate keys
    missing_data = {
        key: item
        for item in data
        if (key := model_dict_key(item, *key_fields)) not in existing_keys
    }
    missing = [build_model(cls, item) for item in missing_data.values()]
    missing = cls.objects.bulk_create(missing, ignore_conflicts=True)
    # Select all objects again in case there ware any conflicts
    return list(cls.objects.select_for_update().filter(query).order_by('id'))


def make_model_field_dict[T: Model](
    instances: Iterable[T],
    *key_fields: str,
) -> dict[ModelKey[object], T]:
    """Map model instances by selected field values.

    Args:
        instances (Iterable[T]): Model instances to index.
        *key_fields (str): Field names used to build dictionary keys.

    Returns:
        dict[ModelKey[object], T]: Instances keyed by field values.
    """
    return {model_object_key(obj, *key_fields): obj for obj in instances}


def get_or_create_model_field_dict[T: Model](
    cls: type[T],
    data: Iterable[dict[str, Any]],
    *key_fields: str,
) -> dict[ModelKey[object], T]:
    """Get or create models and map them by selected fields.

    Args:
        cls (type[T]): The Django model class.
        data (Iterable[dict[str, Any]]): Model data dictionaries.
        *key_fields (str): Field names used to build dictionary keys.

    Returns:
        dict[ModelKey[object], T]: Instances keyed by field values.
    """
    instances = get_or_create_models_by_field(cls, data, *key_fields)
    return make_model_field_dict(instances, *key_fields)


def create_model_field_dict[T: Model](
    cls: type[T],
    data: Iterable[dict[str, Any]],
    *key_fields: str,
) -> dict[ModelKey[object], T]:
    """Create models and map them by selected fields.

    Args:
        cls (type[T]): The Django model class.
        data (Iterable[dict[str, Any]]): Model data dictionaries.
        *key_fields (str): Field names used to build dictionary keys.

    Returns:
        dict[ModelKey[object], T]: Created instances keyed by field values.
    """
    instances = create_models(cls, data)
    return make_model_field_dict(instances, *key_fields)


def locate_model_ids[T: Model](
    cls: type[T],
    items: Iterable[dict[str, Any]],
    _item_id_field: str = 'id',
    _model_id_field: str = 'id',
    **kwargs: object,
) -> set[object]:
    """Locate and lock model IDs referenced by item dictionaries.

    Args:
        cls (type[T]): The Django model class.
        items (Iterable[dict[str, Any]]): Item dictionaries with IDs.
        _item_id_field (str): Field name in each item containing the ID.
        _model_id_field (str): Model field used for lookup.
        **kwargs (object): Additional model lookup filters.

    Returns:
        set[object]: Existing IDs found in the database.

    Raises:
        MissingIdsError: If any requested IDs are not found.
    """
    all_ids = {item[_item_id_field] for item in items}
    kwargs = filter_by_fields(cls, kwargs)
    lookup = {f'{_model_id_field}__in': all_ids} | kwargs
    existing = set(
        cls.objects.select_for_update()
        .filter(**lookup)
        .order_by('id')
        .values_list(_model_id_field, flat=True)
    )
    if missing := all_ids - existing:
        raise MissingIdsError(missing)
    return existing


def locate_model_ids_dict[T: Model](
    cls: type[T],
    items: Iterable[dict[str, Any]],
    _item_id_field: str = 'id',
    _model_id_field: str = 'id',
    **kwargs: object,
) -> dict[ModelKey[object], T]:
    """Locate multiple model instances from an iterable of item dictionaries.

    Retrieves model instances by extracting IDs from item dictionaries and
    looking them up using the specified ID fields. Raises an error if any
    requested items are not found.

    Args:
        cls (type[T]): The Django model class.
        items (Iterable[dict[str, Any]]): List of item dictionaries.
        _item_id_field (str): Field name in item dictionary for the ID.
        _model_id_field (str): Field name on the model for lookup.
        **kwargs (object): Additional filter conditions for the lookup.

    Returns:
        dict[ModelKey[object], T]: Dictionary mapping item ID keys
            to model instances.

    Raises:
        MissingIdsError: If any requested IDs are not found in the database.
    """
    all_ids = {item[_item_id_field] for item in items}
    kwargs = filter_by_fields(cls, kwargs)
    lookup = {f'{_model_id_field}__in': all_ids} | kwargs

    existing = list(
        cls.objects.select_for_update().filter(**lookup).order_by('id')
    )
    existing_ids = {model_object_key(obj, _model_id_field) for obj in existing}

    if missing_ids := all_ids - existing_ids:
        raise MissingIdsError(missing_ids)
    return make_model_field_dict(existing, _model_id_field)


def build_model[T: Model](
    cls: type[T],
    data: dict[str, Any] | None = None,
    **kwargs: object,
) -> T:
    """Build an unsaved model instance from filtered field data.

    Args:
        cls (type[T]): The Django model class.
        data (dict[str, Any] | None): Model data dictionary.
        **kwargs (object): Additional model field values.

    Returns:
        T: Unsaved model instance.
    """
    data = data or {}
    data |= kwargs
    data = filter_by_fields(cls, data)
    return cls(**data)


def create_model[T: Model](
    cls: type[T],
    data: dict[str, Any] | None = None,
    **kwargs: object,
) -> T:
    """Create a model instance using data filtered to model fields.

    Args:
        cls (type[T]): The Django model class.
        data (dict[str, Any] | None): Data to use for creation.
        **kwargs (object): Additional model field values.

    Returns:
        T: The created model instance.
    """
    data = data or {}
    data |= kwargs
    data = filter_by_fields(cls, data)
    return cls.objects.create(**data)


def create_models[T: Model](
    cls: type[T],
    data: Iterable[dict[str, Any]],
) -> list[T]:
    """Create multiple model instances from field dictionaries.

    Args:
        cls (type[T]): The Django model class.
        data (Iterable[dict[str, Any]]): Model data dictionaries.

    Returns:
        list[T]: Created model instances.
    """
    instances = [build_model(cls, item) for item in data]
    return cls.objects.bulk_create(instances)


def get_or_create_model[T: Model](
    cls: type[T],
    defaults: dict[str, object] | None = None,
    *,
    _lock: bool = False,
    **kwargs: object,
) -> T:
    """Get a model instance or create a new one if not exists.

    Args:
        cls (type[T]): The Django model class.
        defaults (dict[str, object] | None): Default values for creation.
        _lock (bool): Whether to lock the retrieved instance for update.
        **kwargs (object): Lookup fields for existing model instance.

    Returns:
        T: The retrieved or newly created model instance.
    """
    defaults = defaults and filter_by_fields(cls, defaults)
    kwargs = filter_by_fields(cls, kwargs)
    queryset = cls.objects
    if _lock:
        queryset = queryset.select_for_update().order_by('id')
    item, created = queryset.get_or_create(defaults=defaults, **kwargs)
    if created and _lock:
        lock_model_instance(item)
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


def format_request_data(
    serializer: type[BaseSerializer],
    **kwargs: object,
) -> str:
    """Format serializer data as pretty-printed JSON for email templates.

    Args:
        serializer (type[BaseSerializer]): The serializer class for `data`.
        **kwargs (object): The raw data to validate and serialize.

    Returns:
        str: The serialized JSON string.
    """
    request_data = serialize_dict(serializer, **kwargs)
    return json.dumps(request_data, indent=4)


def verify_user_email(
    request: AnyRequest,
    user: User | None,
    email: str | None = None,
) -> str | None:
    """Send email verification mail to user.

    Args:
        request (AnyRequest): The request object.
        user (User | None): The user to send mail to.
        email (str | None): The email address.

    Returns:
        str | None: Email confirmation token generated if any.
    """
    if user is None:
        logger.info('User %s does not exist', email)
        return None
    if user.is_active:
        logger.info('User %s already confirmed', user.email)
        return None

    email = cast(str, user.email)
    token = email_verify_token_gen.make_token(user)
    request_data = format_request_data(
        EmailConfirmSerializer, email=email, token=token
    )
    context = get_verify_context(
        request=request,
        token=token,
        view_name='email-confirm',
        request_type='POST',
        request_data=request_data,
    )
    send_user_verification_mail.delay(email, context)
    return token


def reset_user_password(
    request: AnyRequest,
    user: User | None,
    email: str | None = None,
) -> str | None:
    """Send a password reset email to the given user.

    Args:
        request (AnyRequest): The request object.
        user (User | None): The user who will receive the reset email.
        email (str | None): Optional override email address.

    Returns:
        str | None: Password reset token generated if any.
    """
    if user is None:
        logger.info('User %s does not exist', email)
        return None
    if not user.is_active:
        logger.info('User %s is inactive', user.email)
        return None

    email = cast(str, user.email)
    token = password_reset_token_gen.make_token(user)
    request_data = format_request_data(
        PasswordResetConfirmSerializer,
        email=email,
        password='your_new_password',
        token=token,
    )
    context = get_verify_context(
        request=request,
        token=token,
        view_name='password-reset-confirm',
        request_type='POST',
        request_data=request_data,
    )
    send_password_reset_mail.delay(email, context)
    return token


def notify_order_state_on_commit(request: AnyRequest, order: Order) -> None:
    """Schedule order state notifications after transaction commit.

    Args:
        request (AnyRequest): The request used to build email links.
        order (Order): The order to notify about.
    """
    order_context = get_order_context(request, order)
    notify_order_state.delay_on_commit(order.pk, order_context)


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
            *args (Any): Positional arguments for the decorated function.
            **kwargs (Any): Keyword arguments for the decorated function.

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
        request = httpx.Request('GET', url, stream=httpx.SyncByteStream())
        try:
            content = path.read_bytes()
        except FileNotFoundError:
            return httpx.Response(404, text='File not found', request=request)
        except OSError as exc:
            return httpx.Response(500, text=str(exc), request=request)
        return httpx.Response(
            200,
            content=content,
            headers={'content-length': str(len(content))},
            request=request,
        )

    return wrapper


def convert_web_request_errors[**P](
    func: Callable[P, httpx.Response],
) -> Callable[P, httpx.Response]:
    """Convert HTTPX request failures to application errors.

    Args:
        func (Callable[P, httpx.Response]): Function returning a response.

    Returns:
        Callable[P, httpx.Response]: Wrapped function with normalized errors.
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> httpx.Response:
        """Run the wrapped request and raise application errors on failure.

        Args:
            *args (Any): Positional arguments for the wrapped function.
            **kwargs (Any): Keyword arguments for the wrapped function.

        Returns:
            httpx.Response: Successful response from the wrapped function.

        Raises:
            WebRequestError: If the request fails for a supported reason.
        """
        try:
            response = func(*args, **kwargs)
            response.raise_for_status()
        except httpx.RequestError as e:
            logger.error(
                'Failed to download document from %s',
                e.request and e.request.url.netloc,
                exc_info=e,
            )
            if isinstance(e, httpx.TimeoutException):
                raise WebRequestTimeoutError from e
            if isinstance(e, httpx.ConnectError):
                raise WebRequestConnectError from e
            if isinstance(e, httpx.TooManyRedirects):
                raise WebRequestTooManyRedirectsError from e
            if isinstance(e, httpx.HTTPStatusError):
                status_code = e.response.status_code
                raise WebRequestResponseStatusError(status_code) from e
            raise WebRequestError from e
        return response

    return wrapper


@convert_web_request_errors
@debug_process_file_url
def retry_get_url(url: str, retries: int = 10) -> httpx.Response:
    """Retry an HTTP GET request no more than `retries` times.

    Args:
        url (str): The URL to request.
        retries (int): Number of retry attempts before failing.

    Returns:
        httpx.Response: The successful HTTP response.
    """
    with httpx.Client(follow_redirects=True) as session:
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

    Raises:
        YAMLParsingError: If the YAML document cannot be parsed.
    """
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as e:
        logger.error('Invalid YAML document', exc_info=e)
        raise YAMLParsingError(e) from e
    update_shop_pricing(user, url, data)


def make_category_dict(
    data: Iterable[dict[str, Any]],
) -> dict[object, Category]:
    """Map uploaded category IDs to persisted category models.

    Args:
        data (Iterable[dict[str, Any]]): Uploaded category dictionaries.

    Returns:
        dict[object, Category]: Categories keyed by uploaded category ID.
    """
    category_data = [{'name': item['name']} for item in data]
    categories = get_or_create_model_field_dict(
        Category, category_data, 'name'
    )
    return {item['id']: categories[item['name']] for item in data}


@retry_transaction
@transaction.atomic
def update_shop_pricing(user: User, url: str, data: dict[str, Any]) -> None:
    """Apply shop pricing from processed input data.

    Args:
        user (User): The shop owner.
        url (str): Pricing document URL.
        data (dict[str, Any]): Parsed pricing data.
    """
    data = validate_data(ShopPricingSerializer, data)
    name = data['shop']

    try:
        shop = get_and_lock_model(Shop, user=user)
    except Shop.DoesNotExist:
        shop = create_model(Shop, user=user, name=name, url=url)
        lock_model_instance(shop)
    else:
        shop.name = name
        shop.url = url
        shop.save(update_fields=['name', 'url'])

    # Use category IDs from document for in-document mapping only
    categories = make_category_dict(data['categories'])

    # Clear all shop offers but reuse product records
    ShopOffer.objects.filter(shop_id=shop.pk).delete()

    goods = data['goods']
    for item in goods:
        item['category'] = categories[item['category']]
    products = get_or_create_model_field_dict(Product, goods, 'name')

    offer_fields = ('product', 'model')
    for item in goods:
        item['shop'] = shop
        item['product'] = products[item['name']]
    offers = create_model_field_dict(ShopOffer, goods, *offer_fields)

    params_data = [
        {
            'name': name,
            'value': value,
            'offer': offers[model_dict_key(item, *offer_fields)],
        }
        for item in goods
        for name, value in item['parameters'].items()
    ]
    params = get_or_create_model_field_dict(Parameter, params_data, 'name')

    for item in params_data:
        item['parameter'] = params[item['name']]
    create_models(ProductParameter, params_data)


def get_basket_for_update(user: User) -> Basket:
    """Return the user's basket locked for update.

    Args:
        user (User): The basket owner.

    Returns:
        Basket: Locked basket order.
    """
    return get_or_create_model(
        Basket,
        _lock=True,
        user=user,
        state=OrderState.BASKET,
    )


@retry_transaction
@transaction.atomic
def add_to_basket(user: User, items: list[dict[str, Any]]) -> None:
    """Add items to the user's shopping basket from request data.

    Creates a new basket order if needed and adds shop offer items to it.
    If an item is already in the basket, increases its quantity instead
    of creating a duplicate.

    Args:
        user (User): The user adding items to their basket.
        items (list[dict[str, Any]]): Basket item payloads.
    """
    basket = get_basket_for_update(user)
    offer_ids = locate_model_ids(ShopOffer, items, 'shop_offer_id')

    # Remove any duplicate offer ids
    offer_quantity: dict[object, int] = defaultdict(int)
    for item in items:
        offer_id = item['shop_offer_id']
        quantity = item['quantity']
        offer_quantity[offer_id] += quantity

    query = Q(order=basket, shop_offer_id__in=offer_ids)
    existing = list(
        OrderItem.objects.select_for_update().order_by('id').filter(query)
    )
    order_items = {item.shop_offer_id: item for item in existing}

    missing: list[OrderItem] = []

    for offer_id, quantity in offer_quantity.items():
        if order_item := order_items.get(offer_id):
            # If item already in the basket, just increase its quantity
            order_item.quantity += quantity
        else:
            order_item = OrderItem(
                shop_offer_id=offer_id, order=basket, quantity=quantity
            )
            missing.append(order_item)

    if missing:
        OrderItem.objects.bulk_create(missing, ignore_conflicts=True)

    if existing:
        OrderItem.objects.bulk_update(existing, ['quantity'])


@retry_transaction
@transaction.atomic
def edit_basket(user: User, items: list[dict[str, Any]]) -> None:
    """Update quantities of items in the user's shopping basket.

    Modifies the quantity of existing order items in the user's basket
    based on the provided item data.

    Args:
        user (User): The user updating their basket.
        items (list[dict[str, Any]]): Basket item payloads.

    """
    basket = get_basket_for_update(user)
    order_items = locate_model_ids_dict(OrderItem, items, order=basket)
    for item in items:
        order_item = order_items[item['id']]
        order_item.quantity = item['quantity']
    OrderItem.objects.bulk_update(order_items.values(), ['quantity'])


def get_order_state(order_id: object) -> OrderState:
    """Return the persisted state for an order ID.

    Args:
        order_id (object): The order primary key.

    Returns:
        OrderState: The order state stored in the database.
    """
    return Order.objects.only('state').get(pk=order_id).state


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
    order = Order.objects.select_for_update().order_by('id').get(pk=order.pk)
    items = list(OrderItem.objects.filter(order_id=order.pk))

    # Lock all the shop offers
    offer_ids = {item.shop_offer_id for item in items}
    offers = {
        offer.pk: offer
        for offer in (
            ShopOffer.objects.select_for_update()
            .select_related('shop')
            .filter(pk__in=offer_ids)
            .order_by('id')
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


@retry_transaction
@transaction.atomic
def checkout_basket(
    basket: Order,
    contact: Contact,
    notify_request: AnyRequest | None = None,
) -> Order:
    """Perform basket checkout by validating and converting a basket order.

    This function locks the basket and related shop offers, validates that
    all requested quantities are available, and then converts the basket to a
    placed order while deducting inventory quantities.

    Args:
        basket (Order): The basket order to checkout.
        contact (Contact): The contact information for the order.
        notify_request (AnyRequest | None): Request used for notifications.
            If None then no notifications are performed.

    Returns:
        Order: The newly created placed order.

    Raises:
        NotBasketCheckoutError: If the provided order is not a basket.
        BasketCheckoutError: Unable to checkout the provided basket.
    """
    if basket.state != OrderState.BASKET:
        raise NotBasketCheckoutError

    basket, items, offers = _lock_order_items(basket)
    _validate_basket_items(items, offers)

    order = Order.objects.create(
        user_id=basket.user_id,
        contact=contact,
        state=OrderState.NEW,
    )

    _reserve_stock(items, offers)

    # Move basket items to the created order
    order.items.set(items, bulk=True, clear=True)

    if notify_request is not None:
        notify_order_state_on_commit(notify_request, order)

    return order


@retry_transaction
@transaction.atomic
def change_order_state(
    order: Order,
    new_state: OrderState,
    contact: Contact | None = None,
    notify_request: AnyRequest | None = None,
) -> None:
    """Apply an allowed order state transition and update stock.

    Cancelling an order replenishes reserved stock. Reopening a cancelled
    order to the new state reserves stock again.

    Args:
        order (Order): The order to update.
        new_state (OrderState): The requested target state.
        contact (Contact): Optional contact information to set for the order.
        notify_request (AnyRequest | None): Request used for notifications.
            If None then no notifications are performed.

    Raises:
        InvalidOrderStateTransitionError: If the transition is not allowed.
    """
    old_state: OrderState = order.state
    if old_state == new_state:
        return

    validate_order_state_transition(old_state, new_state)
    order, items, offers = _lock_order_items(order)

    # Update shop available stock
    if new_state == OrderState.CANCELLED:
        _replenish_stock(items, offers)
    elif new_state == OrderState.NEW and old_state == OrderState.CANCELLED:
        _validate_basket_items(items, offers)
        _reserve_stock(items, offers)

    order.state = new_state
    update_fields = ['state']
    if contact is not None:
        order.contact = contact
        update_fields.append('contact')
    order.save(update_fields=update_fields)

    if notify_request is not None:
        notify_order_state_on_commit(notify_request, order)


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
