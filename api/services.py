import json
import logging
from typing import Any, cast, override

from django.contrib.auth.models import AbstractBaseUser
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.contrib.sites.shortcuts import get_current_site
from django.core.mail import send_mail
from django.http import HttpRequest
from django.template.loader import render_to_string
from rest_framework.request import Request
from rest_framework.serializers import BaseSerializer
from rest_framework.views import APIView

from .models import User
from .serializers import EmailConfirmSerializer
from .serializers import PasswordResetConfirmSerializer

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


def validate_request(
    cls: type[BaseSerializer],
    view: APIView,
    /,
    raise_exception: bool = True,
) -> dict[str, Any]:
    """Validate serializer data from a view request.

    Args:
        cls (type[BaseSerializer]): The serializer class to use.
        view (APIView): The view containing the request.
        raise_exception (bool): Whether to raise exception on invalid data.

    Returns:
        dict[str, Any]: The validated data.
    """
    request = cast(Request, view.request)
    data = cast(dict[str, Any], request.data)
    return validate_data(cls, data, raise_exception=raise_exception)


def validate_data(
    cls: type[BaseSerializer],
    data: object,
    /,
    raise_exception: bool = True,
) -> dict[str, Any]:
    """Validate data using the given serializer class.

    Args:
        cls (type[BaseSerializer]): The serializer class to use.
        data (object): The data to validate.
        raise_exception (bool): Whether to raise exception on invalid data.

    Returns:
        dict[str, Any]: The validated data.
    """
    serializer: BaseSerializer = cls(data=data)
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


class TokenGenerator(PasswordResetTokenGenerator):
    """Custom token generator for one-time validation codes."""

    def __init__(self, salt: str | None = None) -> None:
        """Initialize the token generator with an optional salt."""
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


def check_email_verify_token(user: User | None, token: str | None):
    """Check if the token is valid for the user.

    Args:
        user (User | None): The user to check.
        token (str | None): The token to validate.

    Returns:
        bool: True if token is valid.
    """
    return email_verify_token_gen.check_token(user, token)


def check_password_reset_token(user: User | None, token: str | None):
    """Check if the password reset token is valid for the user.

    Args:
        user (User | None): The user instance to validate.
        token (str | None): The token string to check.

    Returns:
        bool: True if the token is valid for the given user.
    """
    return password_reset_token_gen.check_token(user, token)


def get_template_context(request: HttpRequest | Request):
    """Build the base context used for email message templates."""
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


def send_email_verification_mail(  # noqa: PLR0913
    request: HttpRequest | Request,
    user: User | None,
    email: str | None = None,
    subject_template: str = 'api/email_verification_subject.txt',
    message_template: str = 'api/email_verification_email.txt',
    html_template: str = 'api/email_verification_email.html',
    from_email: str | None = None,
):
    """Send email verification mail to user.

    Args:
        request (HttpRequest | Request): The request object.
        user (User | None): The user to send mail to.
        email (str | None): The email address.
        subject_template (str): Template for subject.
        message_template (str): Template for plain text message.
        html_template (str): Template for HTML message.
        from_email (str | None): From email address.
    """
    if user is None:
        logger.info('User %s does not exist', email)
        return
    if user.is_active:
        logger.info('User %s already confirmed', user.email)
        return

    email = user.email
    request_type = 'POST'
    token = email_verify_token_gen.make_token(user)
    data = format_request_data(
        {'email': email, 'token': token},
        EmailConfirmSerializer,
    )

    context = get_template_context(request)
    context |= {
        'email': email,
        'user': user,
        'request_type': request_type,
        'request_data': data,
        'token': token,
    }

    render_and_send_mail(
        subject_template=subject_template,
        message_template=message_template,
        html_template=html_template,
        context=context,
        to_email=email,
        from_email=from_email,
    )


def send_password_reset_mail(  # noqa: PLR0913
    request: HttpRequest | Request,
    user: User | None,
    email: str | None = None,
    subject_template: str = 'api/password_reset_subject.txt',
    message_template: str = 'api/password_reset_email.txt',
    html_template: str = 'api/password_reset_email.html',
    from_email: str | None = None,
):
    """Send a password reset email to the given user.

    Args:
        request (HttpRequest | Request): The request object.
        user (User | None): The user who will receive the reset email.
        email (str | None): Optional override email address.
        subject_template (str): Template path for the email subject.
        message_template (str): Template path for the plain text email body.
        html_template (str): Template path for the HTML email body.
        from_email (str | None): Optional from-address for the email.
    """
    if user is None:
        logger.info('User %s does not exist', email)
        return
    if not user.is_active:
        logger.info('User %s is inactive', user.email)
        return

    email = user.email
    request_type = 'POST'
    token = password_reset_token_gen.make_token(user)
    data = format_request_data(
        {'email': email, 'password': 'your_new_password', 'token': token},
        PasswordResetConfirmSerializer,
    )

    context = get_template_context(request)
    context |= {
        'email': email,
        'user': user,
        'request_type': request_type,
        'request_data': data,
        'token': token,
    }

    render_and_send_mail(
        subject_template=subject_template,
        message_template=message_template,
        html_template=html_template,
        context=context,
        to_email=email,
        from_email=from_email,
    )


def render_and_send_mail(  # noqa: PLR0913
    subject_template: str,
    message_template: str,
    context: dict[str, Any],
    to_email: str,
    from_email: str | None = None,
    html_template: str | None = None,
):
    """Send a django.core.mail.EmailMultiAlternatives to `to_email`.

    Args:
        subject_template (str): Path to the email subject template.
        message_template (str): Path to the plain text email body template.
        context (dict[str, Any]): Template context data.
        to_email (str): Recipient email address.
        from_email (str | None): Optional sender email address.
        html_template (str | None): Optional HTML template path.
    """
    subject = render_to_string(subject_template, context)
    # Email subject *must not* contain newlines
    subject = ''.join(subject.splitlines())

    text = render_to_string(message_template, context)
    html = html_template and render_to_string(html_template, context)

    try:
        send_mail(
            subject=subject,
            message=text,
            from_email=from_email,
            recipient_list=[to_email],
            html_message=html,
        )
    except Exception:
        logger.exception('Failed to send email to user %s', context['user'].pk)
