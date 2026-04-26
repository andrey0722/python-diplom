from collections import defaultdict
from collections.abc import Iterable

from django.utils.translation import gettext_lazy as _
from django_stubs_ext import StrPromise
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.exceptions import NotFound


class MissingIdsError(NotFound):
    """Failed to find one or more requested item IDs."""

    def __init__(self, missing_ids: Iterable[object], code: object = None):
        """Initialize the exception with the missing IDs.

        Args:
            missing_ids (Iterable[object]): IDs that were not found.
            code (object, optional): Optional error code.
        """
        detail = {
            'detail': {
                'error': _('One or more ids not found.'),
                'input': list(missing_ids),
            }
        }
        super().__init__(detail, code)


class TokenConfirmError(APIException):
    """Failed to validate user confirmation token."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = _('Invalid email or token.')
    default_code = 'password_reset_error'


class ShopUrlLoadError(APIException):
    """Failed to execute shop pricing URL request."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_detail = _('Could to load shop pricing')
    default_code = 'shop_url_load_error'


class ShopUpdateError(APIException):
    """Unable to apply shop pricing data."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_detail = _('Could not process shop pricing data')
    default_code = 'shop_update_error'


class BasketModifyError(APIException):
    """Unable to modify user's basket contents."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_detail = _('Could not modify basket contents')
    default_code = 'basket_modify_error'


class LazyErrorMessage:
    """Error message class with lazy formatting."""

    def __init__(self, message: 'ErrorMessage', **params: object) -> None:
        """Create a lazy error message that formats later.

        Args:
            message (ErrorMessage): The message template.
            **params (object): Formatting parameters for the message.
        """
        self.message = message
        self.params = params

    def __str__(self) -> str:
        """Format and return the error message.

        Returns:
            str: The formatted error string.
        """
        return str(self.message).format_map(self.params)


type ErrorMessage = str | StrPromise | LazyErrorMessage


class ErrorList(list[ErrorMessage]):
    """List subclass for runtime `isinstance` checks."""


class ErrorDict(defaultdict[str, ErrorList]):
    """Convenience class for collecting field errors."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Set the default factory."""
        super().__init__(ErrorList, *args, **kwargs)


type ErrorDetail = ErrorMessage | ErrorList | ErrorDict


class ApplicationError(Exception):
    """Base class for all application exceptions."""

    default_detail = _('An application error occurred.')
    default_code = 'application_error'

    def __init__(self, detail: ErrorDetail | None = None, code: object = None):
        """Initialize an exception with detail and code.

        Args:
            detail (ErrorDetail | None): The error detail payload.
            code (object, optional): The error code.
        """
        self.detail = self.default_detail if detail is None else detail
        self.code = self.default_code if code is None else code
        super().__init__(self.detail, self.code)


class BasketCheckoutError(ApplicationError):
    """Unable to process basket checkout."""

    default_detail = _('Could not checkout basket.')
    default_code = 'basket_checkout_error'


class NotBasketCheckoutError(BasketCheckoutError):
    """Attempted to checkout a non-basket order."""

    default_detail = _('Not a basket. Only basket can be checked out.')
    default_code = 'not_basket_checkout_error'
