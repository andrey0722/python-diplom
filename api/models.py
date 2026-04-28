import functools
from typing import TYPE_CHECKING, Final, override

from django.contrib import admin
from django.contrib.auth.models import AbstractBaseUser
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth.models import UserManager as BaseUserManager
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import ExpressionWrapper
from django.db.models import F
from django.db.models import IntegerField
from django.db.models import Q
from django.db.models import UniqueConstraint
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _
from model_utils.managers import QueryManager
from phonenumber_field.modelfields import PhoneNumberField
from rest_framework.authtoken.models import Token as BaseToken

if TYPE_CHECKING:
    from django_stubs_ext.db.models.manager import RelatedManager


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


type AnyUser = AbstractBaseUser | AnonymousUser


class User(AbstractUser):
    """Customized user model."""

    objects = UserManager()

    REQUIRED_FIELDS = []
    USERNAME_FIELD = 'email'

    email = models.EmailField(_('email address'), unique=True)
    company = models.CharField(_('company'), max_length=50, blank=True)
    position = models.CharField(_('position'), max_length=50, blank=True)

    @property
    def username(self) -> str:
        """Exclude username field from user model.

        Returns:
            str: Should not be used; exists only for compatibility with
                Django user manager.
        """
        return DUMMY_USERNAME

    @username.setter
    def username(self, _):
        """Dummy setter for username field.

        Args:
            _: Value to set (ignored).
        """

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

    if TYPE_CHECKING:
        user_id: object

    class Meta:
        verbose_name = _('contact')
        verbose_name_plural = _('contacts')

    def __str__(self) -> str:
        """Return the contact address as a formatted string.

        Returns:
            str: The formatted address string.
        """
        return f'{self.user} │ {self.address}'

    @property
    @admin.display(description=_('Address'))
    def address(self) -> str:
        """Return the formatted address string.

        Combines city, street, house number, and apartment into a full address.

        Returns:
            str: Formatted address string.
        """
        house_parts = (self.house, self.structure, self.building)
        house = ' '.join(filter(len, map(str.strip, house_parts)))
        return f'{self.city}, {self.street} {house}, {self.apartment}'

    @property
    @admin.display(description=_('Contact person'))
    def contact_person(self) -> str:
        """Get the contact person's full name.

        Returns the contact person's full name from first/middle/last name
        fields, falling back to the user's full name if no contact person
        name is set.

        Returns:
            str: The contact person's full name.
        """
        name_parts = (self.first_name, self.middle_name, self.last_name)
        name = ' '.join(filter(len, map(str.strip, name_parts)))
        return name or self.user.full_name

    @property
    @admin.display(description=_('Contact email'))
    def contact_email(self) -> str:
        """Return the contact email, falling back to user's email."""
        return self.email or self.user.email


class Category(models.Model):
    """Product category used to group products."""

    name = models.CharField(_('category'), max_length=80)

    if TYPE_CHECKING:
        products: RelatedManager['Product']

    class Meta:
        verbose_name = _('category')
        verbose_name_plural = _('categories')
        constraints = (unique_ignore_case('Category', 'name'),)

    def __str__(self) -> str:
        """Return the category name.

        Returns:
            str: The category name.
        """
        return self.name

    @property
    @admin.display(description=_('Products count'))
    def products_count(self) -> int:
        """Get the number of products in this category.

        Returns:
            int: The count of products.
        """
        return self.products.count()


class Product(models.Model):
    """Product model representing sellable items."""

    name = models.CharField(_('product name'), max_length=120)
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name='products',
        verbose_name=_('category'),
    )

    if TYPE_CHECKING:
        offers: RelatedManager['ShopOffer']

    class Meta:
        verbose_name = _('product')
        verbose_name_plural = _('products')
        constraints = (unique_ignore_case('Product', 'name'),)

    def __str__(self) -> str:
        """Return the product name.

        Returns:
            str: The product name.
        """
        return self.name

    @property
    @admin.display(description=_('Offers count'))
    def offers_count(self) -> int:
        """Get the number of shop offers for this product.

        Returns:
            int: The count of shop offers.
        """
        return self.offers.count()


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

    if TYPE_CHECKING:
        offers: RelatedManager['ShopOffer']

    class Meta:
        verbose_name = _('shop')
        verbose_name_plural = _('shops')
        constraints = (unique_ignore_case('Shop', 'name'),)

    def __str__(self) -> str:
        """Return the shop name.

        Returns:
            str: The shop name.
        """
        return self.name


class Parameter(models.Model):
    """Product parameter type used for shop offers."""

    name = models.CharField(_('parameter name'), max_length=80)

    class Meta:
        verbose_name = _('parameter')
        verbose_name_plural = _('parameters')
        constraints = (unique_ignore_case('Parameter', 'name'),)

    def __str__(self) -> str:
        """Return the parameter name.

        Returns:
            str: The parameter name.
        """
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
        """Return a human-readable representation of the shop offer.

        Returns:
            str: Formatted shop offer string.
        """
        return f'{self.product} │ {self.shop} │ {self.price}'

    @property
    @admin.display(description=_('Discount, %'))
    def discount(self) -> int:
        """Calculate the percentage discount from MSRP to current price.

        Returns:
            int: Discount percentage (0-100).
        """
        fraction = (self.msrp - self.price) / self.msrp if self.msrp else 0
        return int(fraction * 100)

    @property
    @admin.display(
        boolean=True,
        description=_('Active'),
        ordering='shop__is_active',
    )
    def is_active(self) -> bool:
        """Check if the offer's shop is active.

        Returns:
            bool: True if the associated shop is active.
        """
        return self.shop.is_active


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
    value = models.CharField(_('parameter value'), max_length=120)

    class Meta:
        verbose_name = _('product parameter')
        verbose_name_plural = _('product parameters')

    def __str__(self) -> str:
        """Return the product parameter and its value.

        Returns:
            str: Formatted parameter string.
        """
        return f'{self.parameter}: {self.value}'


class OrderState(models.TextChoices):
    """Enumeration of possible order states."""

    # Inactive states
    CANCELLED = 'cancelled', _('Cancelled')
    BASKET = 'basket', _('Basket')

    # Active states
    NEW = 'new', _('New')
    CONFIRMED = 'confirmed', _('Confirmed')
    ASSEMBLED = 'assembled', _('Assembled')
    SENT = 'sent', _('Sent')
    COMPLETED = 'completed', _('Completed')

    @classmethod
    @functools.cache
    def inactive(cls) -> set['OrderState']:
        """Return order states that represent inactive orders."""
        return {cls.BASKET, cls.CANCELLED}

    @classmethod
    @functools.cache
    def active(cls) -> set['OrderState']:
        """Return order states that represent active orders."""
        return set(cls) - cls.inactive()


IS_BASKET: Final = Q(state=OrderState.BASKET)
IS_INACTIVE: Final = Q(state__in=OrderState.inactive())


class Order(models.Model):
    """Order placed by a user with items from different shops."""

    objects = models.Manager()
    inactive = QueryManager(IS_INACTIVE)

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='orders',
        verbose_name=_('user'),
    )
    contact = models.ForeignKey(
        Contact,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name='orders',
        verbose_name=_('contact'),
    )
    state = models.CharField(_('state'), choices=OrderState)

    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    if TYPE_CHECKING:
        user_id: object
        total_sum_value: int
        items: RelatedManager['OrderItem']

    class Meta:
        verbose_name = _('order')
        verbose_name_plural = _('orders')
        constraints = (
            models.UniqueConstraint(
                fields=('user', 'state'),
                condition=IS_BASKET,
                name='uq_order_single_basket',
            ),
            models.CheckConstraint(
                condition=(IS_INACTIVE | Q(contact__isnull=False)),
                name='ck_order_contact_not_null',
            ),
        )

    def __str__(self) -> str:
        """Return order representation with ID and state.

        Returns:
            str: Formatted order string.
        """
        state = OrderState(self.state)
        return f'Order #{self.pk} [{state.label}]'

    @override
    def clean(self):
        """Validate that contact's user matches the order's user."""
        super().clean()
        if self.contact is not None and self.user_id != self.contact.user_id:
            raise ValidationError(
                {'contact': _('Contact must belong to the same user.')}
            )

    @property
    def total_sum(self) -> int:
        """Calculate the total sum of all order items."""
        return sum(x.sum for x in self.items.all())


class Basket(Order):
    """Proxy model for basket orders."""

    objects = QueryManager(IS_BASKET)

    class Meta:  # pyright: ignore[reportIncompatibleVariableOverride]
        proxy = True
        verbose_name = _('Basket')
        verbose_name_plural = _('Baskets')


class PlacedOrder(Order):
    """Proxy model for placed orders."""

    objects = QueryManager(~IS_BASKET)

    class Meta:  # pyright: ignore[reportIncompatibleVariableOverride]
        proxy = True
        verbose_name = _('Order')
        verbose_name_plural = _('Orders')


class OrderItem(models.Model):
    """Line item in an order referencing a specific shop offer."""

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name=_('order'),
    )
    shop_offer = models.ForeignKey(
        ShopOffer,
        on_delete=models.CASCADE,
        related_name='order_items',
        verbose_name=_('shop offer'),
    )
    quantity = models.PositiveIntegerField(_('quantity'))

    if TYPE_CHECKING:
        order_id: object
        shop_offer_id: object

    class Meta:
        verbose_name = _('order item')
        verbose_name_plural = _('order items')
        unique_together = ('order', 'shop_offer')

    def __str__(self) -> str:
        """Return order item representation with order and item ID.

        Returns:
            str: Formatted order item string.
        """
        return f'{self.order} │ Item #{self.pk}'

    @property
    @admin.display(
        description=_('Shop'),
        ordering='shop_offer__shop__name',
    )
    def shop_name(self) -> str:
        """Get the name of the shop in this order item."""
        return self.shop_offer.shop.name

    @property
    @admin.display(
        description=_('Product'),
        ordering='shop_offer__product__name',
    )
    def product_name(self) -> str:
        """Get the name of the product in this order item."""
        return self.shop_offer.product.name

    @property
    @admin.display(description=_('Price'), ordering='shop_offer__price')
    def price(self) -> int:
        """Get the price of the shop offer for this item."""
        return self.shop_offer.price

    @property
    @admin.display(
        description=_('Total sum'),
        ordering=ExpressionWrapper(
            F('shop_offer__price') * F('quantity'),
            output_field=IntegerField(),
        ),
    )
    def sum(self) -> int:
        """Calculate the total sum for this order item."""
        return self.price * self.quantity
