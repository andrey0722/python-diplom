from typing import Any, override

from django.utils.translation import gettext_lazy as _
from django_stubs_ext import StrPromise
from drf_spectacular.drainage import get_override
from drf_spectacular.openapi import AutoSchema as BaseAutoSchema
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample
from drf_spectacular.utils import OpenApiResponse
from rest_framework import status
from rest_framework.serializers import BaseSerializer

from .exceptions import ApplicationError
from .exceptions import ErrorMessage
from .serializers import ApplicationErrorSerializer
from .utils import get_exception_info


class AutoSchema(BaseAutoSchema):
    """Schema generator with customized request body handling."""

    @override
    def get_description(self) -> str:
        """Use only explicit OpenAPI descriptions for operations."""
        return ''

    @override
    def _get_request_body(
        self,
        direction: str = 'request',
    ) -> dict[str, Any] | None:
        """Allow DELETE endpoints to expose request body schemas.

        Args:
            direction (str): Schema direction requested by drf-spectacular.

        Returns:
            dict[str, Any] | None: Request body schema produced
                by the base generator.
        """
        method = self.method.upper()
        if method == 'DELETE':
            # Temporarily substitute the request method
            # to allow request body in the schema for DELETE requests
            self.method = 'POST'
        try:
            return super()._get_request_body(direction)
        finally:
            self.method = method


def _get_exc_attr(exc: Exception | type[Exception], attr: str, alt_attr: str):
    return getattr(exc, attr, getattr(exc, alt_attr, None))


def _find_exc_detail_str(exc: Exception | type[Exception]) -> ErrorMessage:
    if not isinstance(exc, type):
        exc = type(exc)
    for cls in exc.__mro__:
        if detail := _get_exc_attr(cls, 'detail', 'default_detail'):
            return detail
    return ApplicationError.default_detail


def _get_exc_response(
    serializer: type[BaseSerializer],
    exc: Exception | type[Exception],
) -> OpenApiResponse:
    data = {}
    if detail := _get_exc_attr(exc, 'detail', 'default_detail'):
        data['detail'] = detail
    if code := _get_exc_attr(exc, 'code', 'default_code'):
        data['code'] = code

    if not isinstance(detail, str):
        detail = _find_exc_detail_str(exc)

    examples = get_override(serializer, 'examples')
    if not examples:
        # Use error code strings to provide different examples for same status
        name = code and str(code) or 'Response'
        examples = [OpenApiExample(name, value=data, response_only=True)]

    return OpenApiResponse(
        response=serializer,
        description=detail,
        examples=examples,
    )


def error_response_dict(
    *exceptions: Exception | type[Exception],
) -> dict[int, OpenApiResponse]:
    """Build OpenAPI response entries for application exceptions.

    Args:
        *exceptions (Exception | type[Exception]): Exception classes or
            instances to describe.

    Returns:
        dict[int, OpenApiResponse]: Error responses keyed by HTTP status.
    """
    result: dict[int, OpenApiResponse] = {}
    for exc in exceptions:
        info = get_exception_info(exc)
        if info is None:
            continue
        new_response = _get_exc_response(info.serializer, exc)

        if old_response := result.get(info.status_code):
            # Merge example lists
            examples = list(old_response.examples)
            examples += new_response.examples
            old_response.examples = examples
        else:
            # Store response for new status code
            result[info.status_code] = new_response

    return result


def validation_response_dict(
    field: str,
    code: str,
    message: str | StrPromise,
    status_code: int = status.HTTP_400_BAD_REQUEST,
) -> dict[int, OpenApiResponse]:
    """Build an OpenAPI response for a field validation error.

    Args:
        field (str): Field name containing the validation error.
        code (str): Validation error code.
        message (str | StrPromise): Validation error message.
        status_code (int): HTTP status code for the response.

    Returns:
        dict[int, OpenApiResponse]: Validation response keyed by status.
    """
    return {
        status_code: OpenApiResponse(
            response=ApplicationErrorSerializer,
            description=message,
            examples=[
                OpenApiExample(
                    f'validation_{field}_{code}',
                    value={field: [{'message': message, 'code': code}]},
                    response_only=True,
                ),
            ],
        ),
    }


def message_response_dict(
    message: str | StrPromise,
    description: str | StrPromise | None = None,
    status_code: int = status.HTTP_200_OK,
) -> dict[int, OpenApiResponse]:
    """Build an OpenAPI response for a plain message body.

    Args:
        message (str | StrPromise): Example response message.
        description (str | StrPromise | None): Response description.
        status_code (int): HTTP status code for the response.

    Returns:
        dict[int, OpenApiResponse]: Message response keyed by status.
    """
    if description is None:
        description = _('Success.')
    return {
        status_code: OpenApiResponse(
            response=OpenApiTypes.STR,
            description=description,
            examples=[
                OpenApiExample('Response', value=message, response_only=True),
            ],
        ),
    }


def data_response_dict(
    serializer: type[BaseSerializer],
    description: str | StrPromise | None = None,
    status_code: int = status.HTTP_200_OK,
) -> dict[int, OpenApiResponse]:
    """Build an OpenAPI response for a serializer-backed body.

    Args:
        serializer (type[BaseSerializer]): Serializer describing the body.
        description (str | StrPromise | None): Response description.
        status_code (int): HTTP status code for the response.

    Returns:
        dict[int, OpenApiResponse]: Data response keyed by status.
    """
    if description is None:
        description = _('Success.')
    return {
        status_code: OpenApiResponse(
            response=serializer,
            description=description,
            examples=get_override(serializer, 'examples'),
        ),
    }
