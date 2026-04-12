from typing import override

from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as BaseUserManager
from django.db import models
from django.db.models import UniqueConstraint
from django.utils.translation import gettext_lazy as _
from phonenumber_field.modelfields import PhoneNumberField
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

    @property
    def full_name(self) -> str:
        """Return the user's full name."""
        return self.get_full_name()


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


class Contact(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='contacts',
        verbose_name=_('user'),
    )
    first_name = models.CharField(_('first name'), max_length=150, blank=True)
    middle_name = models.CharField(
        _('middle name'),
        max_length=150,
        blank=True,
    )
    last_name = models.CharField(_('last name'), max_length=150, blank=True)
    email = models.EmailField(_('email address'), blank=True)
    phone = PhoneNumberField(_('phone number'))
    city = models.CharField(_('city'), max_length=100)
    street = models.CharField(_('street'), max_length=100)
    house = models.CharField(_('house'), max_length=50)
    structure = models.CharField(_('structure'), max_length=8, blank=True)
    building = models.CharField(_('building'), max_length=8, blank=True)
    apartment = models.CharField(_('apartment'), max_length=8)

    class Meta:
        verbose_name = _('contact')
        verbose_name_plural = _('contacts')

    def __str__(self) -> str:
        """Return the contact address as a formatted string."""
        return self.address

    @property
    def address(self):
        """Return the formatted address string."""
        house_parts = (self.house, self.structure, self.building)
        house = ' '.join(filter(len, map(str.strip, house_parts)))
        return f'{self.city}, {self.street} {house}, {self.apartment}'

    @property
    def contact_person(self):
        """Return the contact person's full name."""
        name_parts = (self.first_name, self.middle_name, self.last_name)
        name = ' '.join(filter(len, map(str.strip, name_parts)))
        return name or self.user.full_name

    @property
    def contact_email(self) -> str:
        """Return the contact email, falling back to user's email."""
        return self.email or self.user.email
