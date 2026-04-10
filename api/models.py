from typing import override

from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as BaseUserManager
from django.db import models
from django.db.models import UniqueConstraint
from django.utils.translation import gettext_lazy as _
from rest_framework.authtoken.models import Token as BaseToken

DUMMY_USERNAME = '_'
"""Use this username for all users since we use email to identify users."""


class UserManager(BaseUserManager):
    """Allows user creation without a username."""

    @override
    def create_user(self, *args, **kwargs):
        """Create user with dummy username."""
        return super().create_user(DUMMY_USERNAME, *args, **kwargs)

    @override
    def create_superuser(self, *args, **kwargs):
        """Create superuser with dummy username."""
        return super().create_superuser(DUMMY_USERNAME, *args, **kwargs)


class User(AbstractUser):
    """Customized user model."""

    objects = UserManager()

    REQUIRED_FIELDS = []
    USERNAME_FIELD = 'email'

    email = models.EmailField(_('email address'), unique=True)
    company = models.CharField(_('company'), max_length=50, blank=True)
    position = models.CharField(_('position'), max_length=50, blank=True)

    username = None
    """Exclude username field from user model."""


class Token(BaseToken):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='auth_tokens',
        verbose_name=_('User'),
    )
    """Override one-to-one with many-to-one."""

    class Meta(BaseToken.Meta):
        abstract = False
        constraints = [
            UniqueConstraint(fields=['key', 'user'], name='uq_key_user'),
        ]
