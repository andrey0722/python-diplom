from typing import override

from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as BaseUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _

DUMMY_USERNAME = '_'
"""Use this username for all users since we use email to identify users."""


class UserManager(BaseUserManager):
    """Allows user creation without a username."""

    @override
    def create_user(self, *args, **kwargs):
        return super().create_user(DUMMY_USERNAME, *args, **kwargs)

    @override
    def create_superuser(self, *args, **kwargs):
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
