from io import BytesIO
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

from django.conf import settings
from django.core.files.base import ContentFile
from django.utils.text import slugify
from PIL import Image
from PIL import UnidentifiedImageError
from social_core.backends.base import BaseAuth
from social_core.backends.google import GoogleOAuth2
from social_core.exceptions import AuthForbidden

from .exceptions import UnverifiedEmailAuthError
from .models import User
from .services import retry_get_url
from .thumbnails import process_user_avatar_updated


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


ALLOWED_AVATAR_CONTENT_TYPES = {
    'image/jpeg': '.jpg',
    'image/png': '.png',
    'image/webp': '.webp',
}


def save_social_avatar(
    backend: BaseAuth,
    user: User | None = None,
    response: dict[str, Any] | None = None,
    *args: Any,  # noqa: ARG001
    **kwargs: Any,  # noqa: ARG001
) -> None:
    """Save a social account avatar for users without avatar.

    Args:
        backend (BaseAuth): Social authentication backend.
        user (User | None): Authenticated user receiving the avatar.
        response (dict[str, Any] | None): Raw backend response data.
        *args (Any): Unused social-auth pipeline arguments.
        **kwargs (Any): Unused social-auth pipeline keyword arguments.
    """
    if user is None or response is None:
        return

    if user.avatar:
        # User already has avatar set
        return

    match backend.name:
        case GoogleOAuth2.name:
            url = response.get('picture')
        case _:
            url = None

    if not url:
        # Could not extract avatar
        return

    file = download_avatar(url)
    if file is None:
        return
    file_name = cast(str, file.name)
    user.avatar.save(file_name, file, save=True)
    process_user_avatar_updated(user)


def download_avatar(url: str) -> ContentFile | None:
    """Download and validate an avatar image from a URL.

    Args:
        url (str): Remote avatar URL.

    Returns:
        ContentFile | None: Downloaded image file, or None if unsupported.
    """
    response = retry_get_url(url)

    header: str = response.headers.get('Content-Type', '')
    content_type = header.split(';', maxsplit=1)[0]
    extension = ALLOWED_AVATAR_CONTENT_TYPES.get(content_type)
    if extension is None:
        return None

    content_length = response.headers.get('Content-Length')
    content_length = content_length and int(content_length)
    if content_length and content_length > settings.MAX_AVATAR_SIZE:
        return None

    content = response.content
    if len(content) > settings.MAX_AVATAR_SIZE:
        return None

    if not validate_image_bytes(content):
        return None

    file_name = Path(urlparse(url).path).name
    file_name = f'{slugify(file_name)}{extension}'
    return ContentFile(content, file_name)


def validate_image_bytes(content: bytes) -> bool:
    """Return whether bytes contain a supported image file.

    Args:
        content (bytes): Image bytes to validate.

    Returns:
        bool: True when Pillow can identify and verify the image.
    """
    try:
        image = Image.open(BytesIO(content))
        image.verify()
    except (UnidentifiedImageError, OSError):
        return False
    return True
