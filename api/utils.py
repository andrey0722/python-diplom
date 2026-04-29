from collections.abc import Callable
from typing import Any, Final, cast

from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.exceptions import ValidationError
from rest_framework.views import Response
from rest_framework.views import exception_handler as drf_exception_handler

from .exceptions import BasketCheckoutError
from .exceptions import InvalidParameterError
from .exceptions import NotBasketCheckoutError
from .exceptions import NotFoundError
from .exceptions import ParsingError
from .exceptions import WebRequestError

EXCEPTION_STATUS_MAPPING: Final[dict[type[Exception], int]] = {
    InvalidParameterError: status.HTTP_400_BAD_REQUEST,
    NotFoundError: status.HTTP_404_NOT_FOUND,
    WebRequestError: status.HTTP_422_UNPROCESSABLE_ENTITY,
    ParsingError: status.HTTP_422_UNPROCESSABLE_ENTITY,
    BasketCheckoutError: status.HTTP_409_CONFLICT,
    NotBasketCheckoutError: status.HTTP_400_BAD_REQUEST,
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
    if response is not None and isinstance(exc, APIException):
        if isinstance(exc, ValidationError):
            # Include 'code' fields for each validation error message
            response.data = exc.get_full_details()
        else:
            # Include 'code' field in the response
            data = cast(dict[str, Any], response.data)
            response.data = {
                'detail': data.get('detail', response.data),
                'code': exc.get_codes(),
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
    status_code = get_exception_status_code(exc)
    if status_code is None:
        return None
    response = Response(status=status_code)
    return prepare_response_data(exc, response)


def get_exception_status_code(exc: Exception) -> int | None:
    """Map a custom application exception to an HTTP status code.

    Args:
        exc (Exception): The exception instance to map.

    Returns:
        int | None: The configured status code for the exception type,
            or None if no mapping exists.
    """
    for cls in type(exc).__mro__:
        if cls in EXCEPTION_STATUS_MAPPING:
            return EXCEPTION_STATUS_MAPPING[cls]
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
