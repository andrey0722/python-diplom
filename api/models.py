from typing import override

from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as BaseUserManager
from django.db import models
from django.db.models import UniqueConstraint
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _
from phonenumber_field.modelfields import PhoneNumberField
from rest_framework.authtoken.models import Token as BaseToken


def unique_ignore_case(model: type[models.Model] | str, *fields: str):
    """Create a case-insensitive unique constraint for model fields.

    Args:
        model (type[models.Model] | str): The model class or table name.
        *fields (str): Field names to include in the constraint.

    Returns:
        UniqueConstraint: A unique constraint using lowercase values.
    """
    if not isinstance(model, str):
        # Get table name from model class object
        model = model._meta.db_table  # noqa: SLF001
    return UniqueConstraint(
        *map(Lower, fields),
        name=f'uq_{model.lower()}_lower_{"_".join(fields)}',
    )


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

    @property
    def username(self):
        """Exclude username field from user model."""

    @username.setter
    def username(self, _):
        """Dummy setter."""

    @property
    def full_name(self) -> str:
        """Return the user's full name."""
        return self.get_full_name()


class Token(BaseToken):
    """Customized token model with many-to-one user relationship."""

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
    """Contact model for user addresses."""

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


class Category(models.Model):
    """Product category used to group products."""

    name = models.CharField(_('category'), max_length=80)

    class Meta:
        verbose_name = _('category')
        verbose_name_plural = _('categories')
        constraints = (unique_ignore_case('Category', 'name'),)

    def __str__(self) -> str:
        """Return the category name."""
        return self.name


class Product(models.Model):
    """Product model representing sellable items."""

    name = models.CharField(_('product name'), max_length=120)
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name='products',
        verbose_name=_('category'),
    )

    class Meta:
        verbose_name = _('product')
        verbose_name_plural = _('products')
        constraints = (unique_ignore_case('Product', 'name'),)

    def __str__(self) -> str:
        """Return the product name."""
        return self.name


class Shop(models.Model):
    """Shop owned by a user with a public product catalog."""

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='shop',
        verbose_name=_('User'),
    )
    name = models.CharField(_('shop name'), max_length=80)
    url = models.URLField(_('update url'), blank=True)
    is_active = models.BooleanField(_('active'), default=True)

    class Meta:
        verbose_name = _('shop')
        verbose_name_plural = _('shops')
        constraints = (unique_ignore_case('Shop', 'name'),)

    def __str__(self) -> str:
        """Return the shop name."""
        return self.name


class Parameter(models.Model):
    """Product parameter type used for shop offers."""

    name = models.CharField(_('parameter name'), max_length=80)

    class Meta:
        verbose_name = _('parameter')
        verbose_name_plural = _('parameters')
        constraints = (unique_ignore_case('Parameter', 'name'),)

    def __str__(self) -> str:
        """Return the parameter name."""
        return self.name


class ShopOffer(models.Model):
    """Offer for a product sold by a shop with pricing and parameters."""

    shop = models.ForeignKey(
        Shop,
        on_delete=models.CASCADE,
        related_name='offers',
        verbose_name=_('shop'),
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='offers',
        verbose_name=_('product'),
    )
    part_number = models.PositiveIntegerField(_('part number'))
    model = models.CharField(_('product model'), max_length=120)
    msrp = models.PositiveIntegerField(_('recommended price'))
    price = models.PositiveIntegerField(_('price'))
    quantity = models.PositiveIntegerField(_('quantity'))

    class Meta:
        verbose_name = _('shop offer')
        verbose_name_plural = _('shop offers')
        unique_together = ('shop', 'product', 'model')

    def __str__(self) -> str:
        """Return a human-readable representation of the shop offer."""
        return f'[{self.shop}] {self.product}: {self.price}'


class ProductParameter(models.Model):
    """Instance of a parameter with a concrete value for a product."""

    parameter = models.ForeignKey(
        Parameter,
        on_delete=models.CASCADE,
        related_name='product_parameters',
        verbose_name=_('parameter'),
    )
    offer = models.ForeignKey(
        ShopOffer,
        on_delete=models.CASCADE,
        related_name='parameters',
        verbose_name=_('offers'),
    )
    value = models.CharField(_('product model'), max_length=120)

    def __str__(self) -> str:
        """Return the product parameter and its value."""
        return f'{self.parameter}: {self.value}'
