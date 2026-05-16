import enum
from typing import cast

from django.db.models.fields.files import ImageFieldFile
from easy_thumbnails.files import Thumbnailer
from easy_thumbnails.files import get_thumbnailer

from .models import User
from .tasks import delete_avatar_with_thumbnails
from .tasks import generate_user_avatar_thumbnails


class AvatarSize(enum.StrEnum):
    """Named thumbnail aliases for user avatars."""

    SMALL = 'avatar_small'
    MEDIUM = 'avatar_medium'
    LARGE = 'avatar_large'


def get_user_avatar(user: User) -> str | None:
    """Return the stored avatar name for a user.

    Args:
        user (User): User whose avatar should be read.

    Returns:
        str | None: Stored avatar name, or None when no avatar exists.
    """
    return user.avatar.name if user.avatar else None


def load_user_avatar(user_id: object) -> str | None:
    """Load a user's stored avatar name from the database.

    Args:
        user_id (object): User primary key.

    Returns:
        str | None: Stored avatar name, or None when no avatar exists.
    """
    return (
        User.objects.filter(pk=user_id)
        .values_list('avatar', flat=True)
        .first()
    )


def get_avatar_thumbnail(
    avatar: ImageFieldFile,
    size: AvatarSize,
) -> ImageFieldFile | None:
    """Return an avatar thumbnail for the requested size.

    Args:
        avatar (ImageFieldFile): Source avatar image.
        size (AvatarSize): Thumbnail alias to load.

    Returns:
        ImageFieldFile | None: Thumbnail file, or None if unavailable.
    """
    thumbnailer = cast(Thumbnailer, get_thumbnailer(avatar))
    try:
        return thumbnailer[size]
    except Exception:
        return None


def get_user_avatar_thumbnail(
    user: User,
    size: AvatarSize,
) -> ImageFieldFile | None:
    """Return a user's avatar thumbnail for the requested size.

    Args:
        user (User): User whose avatar thumbnail should be read.
        size (AvatarSize): Thumbnail alias to load.

    Returns:
        ImageFieldFile | None: Thumbnail file, or None if unavailable.
    """
    return get_avatar_thumbnail(user.avatar, size)


def get_user_avatar_thumbnail_url(user: User, size: AvatarSize) -> str | None:
    """Return a user's avatar thumbnail URL for the requested size.

    Args:
        user (User): User whose avatar thumbnail URL should be read.
        size (AvatarSize): Thumbnail alias to load.

    Returns:
        str | None: Thumbnail URL, or None if unavailable.
    """
    thumbnail = get_user_avatar_thumbnail(user, size)
    return thumbnail.url if thumbnail else None


def get_user_avatar_url(user: User, preferred_size: AvatarSize) -> str | None:
    """Return the best available avatar URL for a user.

    Args:
        user (User): User whose avatar URL should be read.
        preferred_size (AvatarSize): Thumbnail alias preferred by caller.

    Returns:
        str | None: Preferred thumbnail URL or original avatar URL.
    """
    if not user.avatar_thumbnails_ready:
        return user.avatar.url
    return get_user_avatar_thumbnail_url(user, preferred_size)


def process_user_avatar_updated(
    user: User,
    old_avatar: str | None = None,
) -> None:
    """Schedule thumbnail generation and old avatar cleanup when needed.

    Args:
        user (User): User whose avatar may have changed.
        old_avatar (str | None): Previously stored avatar name.
    """
    new_avatar = get_user_avatar(user)
    if old_avatar == new_avatar:
        # Avatar not changed, nothing to do
        return

    if user.avatar_thumbnails_ready:
        # Reset ready state for a new avatar thumbnails
        user.avatar_thumbnails_ready = False
        user.save(update_fields=['avatar_thumbnails_ready'])

    # Schedule async postprocessing
    if new_avatar:
        generate_user_avatar_thumbnails.delay_on_commit(user.pk, new_avatar)
    if old_avatar:
        delete_avatar_with_thumbnails.delay_on_commit(old_avatar)
