from typing import Any

from social_core.backends.base import BaseAuth
from social_core.backends.google import GoogleOAuth2
from social_core.exceptions import AuthForbidden

from .exceptions import UnverifiedEmailAuthError


def require_verified_email(
    backend: BaseAuth,
    details: dict[str, Any],
    response: dict[str, Any],
    *args: Any,  # noqa: ARG001
    **kwargs: Any,  # noqa: ARG001
) -> dict[str, Any] | None:
    """Allow social login only for supported verified-email providers.

    Args:
        backend (BaseAuth): Social authentication backend.
        details (dict[str, Any]): User details returned by the backend.
        response (dict[str, Any]): Raw backend response data.
        *args (Any): Unused social-auth pipeline arguments.
        **kwargs (Any): Unused social-auth pipeline keyword arguments.

    Returns:
        dict[str, Any] | None: None when the pipeline may continue.

    Raises:
        UnverifiedEmailAuthError: If Google does not provide a verified
            email address.
        AuthForbidden: If the backend is not supported by this pipeline.
    """
    match backend.name:
        case GoogleOAuth2.name:
            email = details.get('email')
            email_verified = response.get('email_verified')
            if not email or not email_verified:
                raise UnverifiedEmailAuthError(backend)
            return None

    raise AuthForbidden(backend)
