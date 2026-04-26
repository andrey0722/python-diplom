from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _

from .models import Category
from .models import Contact
from .models import Order
from .models import OrderItem
from .models import Parameter
from .models import Product
from .models import ProductParameter
from .models import Shop
from .models import ShopOffer
from .models import Token
from .models import User


class ContactsInline(admin.StackedInline):
    """Inline admin for Contact model."""

    model = Contact
    extra = 0


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Django admin configuration for User model."""

    list_display = (
        'email',
        'full_name',
        'last_login',
        'date_joined',
        'is_active',
        'is_staff',
    )
    list_editable = ('is_active',)
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        (
            _('Personal info'),
            {
                'fields': (
                    'first_name',
                    'last_name',
                    'company',
                    'position',
                ),
            },
        ),
        (
            _('Permissions'),
            {
                'fields': (
                    'is_active',
                    'is_staff',
                    'is_superuser',
                    'groups',
                    'user_permissions',
                ),
            },
        ),
        (_('Important dates'), {'fields': ('last_login', 'date_joined')}),
    )
    ordering = ('email',)
    inlines = (ContactsInline,)
    save_on_top = True


@admin.register(Token)
class TokenAdmin(admin.ModelAdmin):
    """Admin configuration for Token model."""

    list_display = ('key', 'user', 'created')
    list_filter = ('created',)
    search_fields = (f'user__{User.USERNAME_FIELD}',)
    search_help_text = _('User')
    ordering = (f'user__{User.USERNAME_FIELD}',)


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    """Admin configuration for Contact model."""

    list_display = (
        'address',
        'user',
        'contact_person',
        'contact_email',
        'phone',
    )
    list_filter = ('city', 'user')
    search_fields = (
        f'user__{User.USERNAME_FIELD}',
        'email',
        'phone',
        'first_name',
        'middle_name',
        'last_name',
        'city',
        'street',
        'house',
        'structure',
        'building',
        'apartment',
    )
    fieldsets = (
        (None, {'fields': ('user',)}),
        (
            _('Contacts'),
            {
                'fields': ('phone', 'email'),
            },
        ),
        (
            _('Personal info'),
            {
                'fields': ('first_name', 'middle_name', 'last_name'),
            },
        ),
        (
            _('Address'),
            {
                'fields': (
                    'city',
                    'street',
                    'house',
                    'structure',
                    'building',
                    'apartment',
                ),
            },
        ),
    )
    save_on_top = True


class ProductsInline(admin.TabularInline):
    """Inline admin for Product model."""

    model = Product
    extra = 0


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    """Admin configuration for Category model."""

    list_display = ('name', 'products_count')
    inlines = (ProductsInline,)
    save_on_top = True


class OffersInline(admin.StackedInline):
    """Inline admin for ShopOffer model."""

    model = ShopOffer
    extra = 0


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    """Admin configuration for Product model."""

    list_display = ('name', 'offers_count')
    inlines = (OffersInline,)
    save_on_top = True


@admin.register(Shop)
class ShopAdmin(admin.ModelAdmin):
    """Admin configuration for Shop model."""

    list_display = ('name', 'user', 'is_active')
    list_filter = ('is_active',)
    list_editable = ('is_active',)
    search_fields = ('name', f'user__{User.USERNAME_FIELD}')
    inlines = (OffersInline,)
    save_on_top = True


@admin.register(Parameter)
class ParameterAdmin(admin.ModelAdmin):
    """Admin configuration for Parameter model."""

    list_display = ('name',)
    search_fields = ('name',)


class ProductParametersInline(admin.TabularInline):
    """Inline admin for ProductParameter model."""

    model = ProductParameter
    extra = 0


@admin.register(ShopOffer)
class ShopOfferAdmin(admin.ModelAdmin):
    """Admin configuration for ShopOffer model."""

    list_display = (
        'product',
        'shop',
        'part_number',
        'price',
        'discount',
        'quantity',
        'is_active',
    )
    list_filter = ('shop__name',)
    search_fields = ('shop__name', 'product__name', 'part_number')
    inlines = (ProductParametersInline,)
    save_on_top = True


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    """Admin configuration for OrderItem model."""

    list_display = (
        'id',
        'order',
        'order__user',
        'quantity',
        'shop_offer__price',
        'shop_offer__shop',
    )
    list_filter = ('order__state', 'shop_offer__shop__name')
    search_fields = ('id', 'order__id', f'order__user__{User.USERNAME_FIELD}')
    save_on_top = True


class OrderItemsInline(admin.StackedInline):
    """Inline admin for OrderItem model."""

    model = OrderItem
    extra = 0


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    """Admin configuration for Order model."""

    list_display = (
        'id',
        'user',
        'state',
        'contact',
        'created_at',
        'updated_at',
    )
    list_filter = ('state',)
    search_fields = ('id', f'user__{User.USERNAME_FIELD}')
    inlines = (OrderItemsInline,)
    save_on_top = True
