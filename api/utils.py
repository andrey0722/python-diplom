from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final, cast

from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.exceptions import NotAuthenticated
from rest_framework.exceptions import NotFound
from rest_framework.exceptions import PermissionDenied
from rest_framework.exceptions import Throttled
from rest_framework.exceptions import ValidationError
from rest_framework.serializers import BaseSerializer
from rest_framework.views import Response
from rest_framework.views import exception_handler as drf_exception_handler

from .exceptions import BasketCheckoutError
from .exceptions import InvalidOrderStateTransitionError
from .exceptions import InvalidParameterError
from .exceptions import LoginError
from .exceptions import MissingIdsError
from .exceptions import NotBasketCheckoutError
from .exceptions import NotFoundError
from .exceptions import ParsingError
from .exceptions import WebRequestError
from .serializers import ApplicationErrorSerializer
from .serializers import MissingIdsErrorSerializer


@dataclass(frozen=True)
class ExceptionInfo:
    """Exception-to-response mapping entry."""

    status_code: int
    serializer: type[BaseSerializer] = ApplicationErrorSerializer


EXCEPTION_REGISTRY: Final[dict[type[Exception], ExceptionInfo]] = {
    InvalidParameterError: ExceptionInfo(status.HTTP_400_BAD_REQUEST),
    LoginError: ExceptionInfo(status.HTTP_401_UNAUTHORIZED),
    NotFoundError: ExceptionInfo(status.HTTP_404_NOT_FOUND),
    MissingIdsError: ExceptionInfo(
        status_code=status.HTTP_404_NOT_FOUND,
        serializer=MissingIdsErrorSerializer,
    ),
    WebRequestError: ExceptionInfo(status.HTTP_422_UNPROCESSABLE_ENTITY),
    ParsingError: ExceptionInfo(status.HTTP_422_UNPROCESSABLE_ENTITY),
    BasketCheckoutError: ExceptionInfo(status.HTTP_409_CONFLICT),
    NotBasketCheckoutError: ExceptionInfo(status.HTTP_400_BAD_REQUEST),
    InvalidOrderStateTransitionError: ExceptionInfo(
        status.HTTP_400_BAD_REQUEST
    ),
    # DRF errors
    AuthenticationFailed: ExceptionInfo(AuthenticationFailed.status_code),
    NotAuthenticated: ExceptionInfo(NotAuthenticated.status_code),
    PermissionDenied: ExceptionInfo(PermissionDenied.status_code),
    NotFound: ExceptionInfo(NotFound.status_code),
    Throttled: ExceptionInfo(Throttled.status_code),
}


def exception_handler(
    exc: Exception,
    context: dict[str, Any],
) -> Response | None:
    """Run registered exception handlers and return the first response.

    Args:
        exc (Exception): The exception raised during request processing.
        context (dict[str, Any]): The DRF exception context.

    Returns:
        Response | None: Response produced by a registered handler,
            or None if no handler was able to handle the exception.
    """
    for handler in handlers:
        response = handler(exc, context)
        if response is not None:
            return response

    # Exception in unhandled
    return None


type Handler = Callable[[Exception, dict[str, Any]], Response | None]

handlers: list[Handler] = []


def register_handler(func: Handler) -> Handler:
    """Register a custom exception handler.

    Args:
        func (Handler): The exception handler to register.

    Returns:
        Handler: The same handler function, for decorator usage.
    """
    handlers.append(func)
    return func


@register_handler
def standard_exception_handler(
    exc: Exception,
    context: dict[str, Any],
) -> Response | None:
    """Handle standard DRF exceptions and include error codes.

    Args:
        exc (Exception): The exception to convert into a response.
        context (dict[str, Any]): The DRF exception context.

    Returns:
        Response | None: The DRF response object, or None if not handled.
    """
    response = drf_exception_handler(exc, context)
    if response is not None:
        data = cast(dict[str, Any], response.data)
        if isinstance(exc, ValidationError):
            # Include 'code' fields for each validation error message
            response.data = exc.get_full_details()
        elif isinstance(exc, APIException):
            # Include 'code' field in the response
            response.data = {
                'detail': data.get('detail', response.data),
                'code': exc.get_codes(),
            }
        else:
            detail = data.get('detail', data)
            if hasattr(detail, 'code'):
                # Include 'code' field in the response
                response.data = {
                    'detail': detail,
                    'code': detail.code,
                }

    return response


@register_handler
def custom_exception_handler(
    exc: Exception,
    context: dict[str, Any],  # noqa: ARG001
) -> Response | None:
    """Handle custom application exceptions with explicit status codes.

    Args:
        exc (Exception): The exception to handle.
        context (dict[str, Any]): The DRF exception context.

    Returns:
        Response | None: A normalized response for application errors,
            or None if the exception is not mapped.
    """
    info = get_exception_info(exc)
    if info is None:
        return None
    response = Response(status=info.status_code)
    return prepare_response_data(exc, response)


def get_exception_info(
    exc: Exception | type[Exception],
) -> ExceptionInfo | None:
    """Map a custom application exception to an HTTP status code.

    Args:
        exc (Exception | type[Exception]): The exception instance
            or class to map.

    Returns:
        ExceptionInfo | None: The configured mapping for the exception type,
            or None if no mapping exists.
    """
    if not isinstance(exc, type):
        exc = type(exc)
    for cls in exc.__mro__:
        if cls in EXCEPTION_REGISTRY:
            return EXCEPTION_REGISTRY[cls]
    return None


def prepare_response_data(exc: Exception, response: Response) -> Response:
    """Populate response data fields from exception attributes.

    Args:
        exc (Exception): The exception containing detail or code attributes.
        response (Response): The response object to fill.

    Returns:
        Response: The response object with normalized data.
    """
    data = cast(dict[str, Any], response.data) or {}
    for field in 'detail', 'code':
        add_response_field(exc, data, field)
    response.data = data
    return response


def add_response_field(
    exc: Exception,
    data: dict[str, Any],
    field: str,
) -> None:
    """Add a response field from an exception if not already present.

    Args:
        exc (Exception): The exception providing additional response fields.
        data (dict[str, Any]): The response data dictionary.
        field (str): The response field name to add.
    """
    try:
        value = data[field]
    except KeyError:
        try:
            value = getattr(exc, field)
        except AttributeError:
            return
        data[field] = value
