from collections import defaultdict
from collections.abc import Iterable

from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _
from django_stubs_ext import StrPromise
import yaml

from .models import OrderState


class LazyErrorMessage(Promise):
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


def lazy_str(obj: object) -> LazyErrorMessage:
    """Wrap an object for lazy string conversion.

    Args:
        obj (object): The object to stringify lazily.

    Returns:
        LazyErrorMessage: Lazy message wrapper for the object.
    """
    return LazyErrorMessage('{obj!s}', obj=obj)


type ErrorMessage = str | StrPromise | LazyErrorMessage


class ErrorList(list[ErrorMessage]):
    """List subclass for runtime `isinstance` checks."""


class ErrorDict(defaultdict[str, ErrorList]):
    """Convenience class for collecting field errors."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Set the default factory.

        Args:
            *args (object): Positional dictionary arguments.
            **kwargs (object): Keyword dictionary arguments.
        """
        super().__init__(ErrorList, *args, **kwargs)


class ErrorPlainDict(dict[str, 'ErrorDetail']):
    """Convenience class for free-form error data."""


type ErrorDetail = ErrorMessage | ErrorList | ErrorDict | ErrorPlainDict | None
type ErrorCode = str | None


class ApplicationError(Exception):
    """Base class for all application exceptions."""

    default_detail = _('An application error occurred.')
    default_code = 'application_error'

    def __init__(self, detail: ErrorDetail = None, code: ErrorCode = None):
        """Initialize an exception with detail and code.

        Args:
            detail (ErrorDetail): The error detail payload.
            code (ErrorCode): The error code.
        """
        self.detail = self.default_detail if detail is None else detail
        self.code = self.default_code if code is None else code
        super().__init__(self.detail, self.code)


class InvalidParameterError(ApplicationError):
    """Request contains an invalid parameter."""

    default_detail = _('Invalid parameter has been passed to the request.')
    default_code = 'invalid_parameter_error'


class NotFoundError(ApplicationError):
    """Requested application resource was not found."""

    default_detail = _('Requested resource not found.')
    default_code = 'not_found_error'


class WebRequestError(ApplicationError):
    """Failed to execute web request."""

    default_detail = _('Could not execute web request.')
    default_code = 'web_request_error'


class WebRequestTimeoutError(WebRequestError):
    """Failed to execute web request due to timeout."""

    default_detail = _('The remote server did not respond in time.')
    default_code = 'web_request_timeout_error'


class WebRequestConnectError(WebRequestError):
    """Failed to connect to a remote server."""

    default_detail = _('Could not connect to the remote server.')
    default_code = 'web_request_connect_error'


class WebRequestTooManyRedirectsError(WebRequestError):
    """Remote URL redirected too many times."""

    default_detail = _('The URL redirects too many times.')
    default_code = 'web_request_too_many_redirects_error'


class WebRequestResponseStatusError(WebRequestError):
    """Remote server returned an unsuccessful status code."""

    default_detail = _(
        'The remote server responded with status code {status_code}.'
    )
    default_code = 'web_request_response_status_error'

    def __init__(self, status_code: int, code: ErrorCode = None):
        """Initialize the error with the remote response status.

        Args:
            status_code (int): HTTP status code returned by the server.
            code (ErrorCode): Optional error code override.
        """
        detail = LazyErrorMessage(self.default_detail, status_code=status_code)
        super().__init__(detail, code)


class ParsingError(ApplicationError):
    """Input document could not be parsed."""

    default_detail = _('Could not parse input document.')
    default_code = 'parsing_error'


class YAMLParsingError(ParsingError):
    """YAML input document could not be parsed."""

    default_detail = _('The input document is not a valid YAML.')
    default_code = 'yaml_parsing_error'

    def __init__(self, exc: yaml.YAMLError, code: ErrorCode = None):
        """Initialize the error with safe YAML parser details.

        Args:
            exc (yaml.YAMLError): YAML parser exception.
            code (ErrorCode): Optional error code override.
        """
        detail = ErrorPlainDict()
        detail['error'] = self.default_detail
        if problem := getattr(exc, 'problem', None):
            detail['reason'] = str(problem)[:200]
        if mark := getattr(exc, 'problem_mark', None):
            detail['line'] = mark.line + 1
            detail['column'] = mark.column + 1
        super().__init__(detail, code)


class TokenConfirmError(InvalidParameterError):
    """Failed to validate user confirmation token."""

    default_detail = _('Invalid email or token provided.')
    default_code = 'token_confirm_error'


class MissingIdsError(NotFoundError):
    """Failed to find one or more requested item IDs."""

    default_detail = _('One or more ids not found.')
    default_code = 'missing_ids_error'

    def __init__(self, missing_ids: Iterable[object], code: ErrorCode = None):
        """Initialize the exception with the missing IDs.

        Args:
            missing_ids (Iterable[object]): IDs that were not found.
            code (ErrorCode): The error code.
        """
        detail = ErrorPlainDict()
        detail['error'] = self.default_detail
        detail['input'] = ErrorList(map(lazy_str, missing_ids))
        super().__init__(detail, code)


class BasketCheckoutError(ApplicationError):
    """Unable to process basket checkout."""

    default_detail = _('Could not checkout basket.')
    default_code = 'basket_checkout_error'


class NotBasketCheckoutError(BasketCheckoutError):
    """Attempted to checkout a non-basket order."""

    default_detail = _('Not a basket. Only basket can be checked out.')
    default_code = 'not_basket_checkout_error'


class InvalidOrderStateTransitionError(ApplicationError):
    """Unable to change order state in this direction."""

    default_code = 'invalid_order_state_transition_error'

    def __init__(
        self,
        old: OrderState,
        new: OrderState,
        code: ErrorCode = None,
    ):
        """Initialize the error with source and target order states.

        Args:
            old (OrderState): The current order state.
            new (OrderState): The requested order state.
            code (ErrorCode): Optional error code override.
        """
        detail = LazyErrorMessage(
            _('Cannot change order state from {old!r} to {new!r}'),
            old=old,
            new=new,
        )
        super().__init__(detail, code)
