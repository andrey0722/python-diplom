from typing import Any, override

from admin_extra_buttons.decorators import button
from admin_extra_buttons.mixins import ExtraButtonsMixin
from django.contrib import admin
from django.contrib import messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import F
from django.db.models import IntegerField
from django.db.models import Model
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.forms import ModelForm
from django.http import HttpRequest
from django.http import HttpResponse
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from .exceptions import ApplicationError
from .exceptions import ErrorDict
from .exceptions import ErrorList
from .forms import BasketAdminForm
from .forms import OrderAdminForm
from .forms import OrderItemInlineFormSet
from .forms import UserContactSelectForm
from .models import Basket
from .models import Category
from .models import Contact
from .models import Order
from .models import OrderItem
from .models import OrderState
from .models import Parameter
from .models import PlacedOrder
from .models import Product
from .models import ProductParameter
from .models import Shop
from .models import ShopOffer
from .models import Token
from .models import User
from .services import change_order_state
from .services import checkout_basket
from .services import get_order_state
from .services import is_order_active


def get_admin_view(
    model_cls: type[Model],
    view: str,
    *args: object,
    **query: object,
):
    """Build the reverse URL for an admin view.

    Args:
        model_cls (type[Model]): The model class for the admin view.
        view (str): The view name (e.g., 'change', 'changelist').
        *args (object): Positional arguments for the URL.
        **query (object): Query parameters for the URL.

    Returns:
        str: The reversed admin URL.
    """
    meta = model_cls._meta  # noqa: SLF001
    app = meta.app_label
    model = meta.model_name
    return reverse(f'admin:{app}_{model}_{view}', args=args, query=query)


def redirect_admin_view(
    model_cls: type[Model],
    view: str,
    *args: object,
    **query: object,
):
    """Redirect to an admin view URL.

    Args:
        model_cls (type[Model]): The model class for the admin view.
        view (str): The admin view name.
        *args (object): Positional arguments for the URL.
        **query (object): Query parameters for the URL.

    Returns:
        HttpResponseRedirect: Redirect response to the admin URL.
    """
    url = get_admin_view(model_cls, view, *args, **query)
    return HttpResponseRedirect(url)


def app_error_message(request: HttpRequest, e: ApplicationError) -> None:
    """Display error messages for application-specific exceptions.

    Args:
        request (HttpRequest): The current HTTP request.
        e (ApplicationError): The application error to display.
    """
    detail = e.detail
    if isinstance(detail, ErrorDict):
        for field, errors in detail.items():
            for error in errors:
                messages.error(request, f'{field}: {error}')
    elif isinstance(detail, ErrorList):
        for error in detail:
            messages.error(request, str(error))
    else:
        messages.error(request, str(detail))


def error_message(request: HttpRequest, exc: Exception) -> None:
    """Display a generic error message for any exception.

    Args:
        request (HttpRequest): The current HTTP request.
        exc (Exception): The exception to display.
    """
    if isinstance(exc, ApplicationError):
        app_error_message(request, exc)
    else:
        messages.error(request, str(exc))


class DisableModelAddMixin(admin.ModelAdmin):
    """Admin mixin that blocks model add views."""

    @override
    def has_add_permission(self, request: HttpRequest) -> bool:
        """Disable the add permission for this admin model.

        Args:
            request (HttpRequest): The current admin request.

        Returns:
            bool: Always False.
        """
        return False

    @override
    def add_view(
        self,
        request: HttpRequest,
        form_url: str = '',
        extra_context: dict[str, Any] | None = None,
    ) -> HttpResponse:
        """Reject direct access to the add view.

        Args:
            request (HttpRequest): The current admin request.
            form_url (str): The add form URL path.
            extra_context (dict[str, Any] | None): Extra template context.

        Raises:
            PermissionDenied: Always raised for this admin view.
        """
        raise PermissionDenied


class ContactsInline(admin.StackedInline):
    """Inline admin for Contact model."""

    model = Contact
    extra = 0


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Django admin configuration for User model."""

    list_display = (
        'id',
        'email',
        'full_name',
        'last_login',
        'date_joined',
        'is_active',
        'is_staff',
    )
    list_display_links = ('id', 'email')
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
        'id',
        'product',
        'shop',
        'part_number',
        'price',
        'discount',
        'quantity',
        'is_active',
    )
    list_filter = ('shop__name',)
    search_fields = ('id', 'shop__name', 'product__name', 'part_number')
    inlines = (ProductParametersInline,)
    save_on_top = True


@admin.register(OrderItem)
class OrderItemAdmin(DisableModelAddMixin, admin.ModelAdmin):
    """Admin configuration for OrderItem model."""

    list_display = (
        'id',
        'order',
        'order__user',
        'product_name',
        'quantity',
        'price',
        'sum',
        'shop_name',
    )
    list_filter = ('order__state', 'shop_offer__shop__name')
    search_fields = ('id', 'order__id', f'order__user__{User.USERNAME_FIELD}')
    readonly_fields = ('order',)
    save_on_top = True

    @override
    def has_change_permission(
        self,
        request: HttpRequest,
        obj: OrderItem | None = None,
    ) -> bool:
        """Allow editing only for items outside active orders.

        Args:
            request (HttpRequest): The current admin request.
            obj (OrderItem | None): The order item being edited.

        Returns:
            bool: True when the item may be changed.
        """
        return super().has_change_permission(
            request, obj
        ) and self._is_order_item_editable(obj)

    @override
    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: OrderItem | None = None,
    ) -> bool:
        """Allow deletion only for items outside active orders.

        Args:
            request (HttpRequest): The current admin request.
            obj (OrderItem | None): The order item being deleted.

        Returns:
            bool: True when the item may be deleted.
        """
        return super().has_delete_permission(
            request, obj
        ) and self._is_order_item_editable(obj)

    @staticmethod
    def _is_order_item_editable(item: OrderItem | None) -> bool:
        """Return whether an order item belongs to an editable order.

        Args:
            item (OrderItem | None): The order item to check.

        Returns:
            bool: True when the related order is not active.
        """
        return not is_order_active(item and item.order_id)


class OrderItemsInline(admin.StackedInline):
    """Inline admin for OrderItem model."""

    model = OrderItem
    formset = OrderItemInlineFormSet
    extra = 0

    @override
    def has_add_permission(
        self,
        request: HttpRequest,
        obj: Order | None = None,
    ) -> bool:
        """Allow inline item creation only for editable orders.

        Args:
            request (HttpRequest): The current admin request.
            obj (Order | None): The parent order.

        Returns:
            bool: True when new inline items may be added.
        """
        return super().has_add_permission(
            request, obj
        ) and self._is_order_editable(obj)

    @override
    def has_change_permission(
        self,
        request: HttpRequest,
        obj: Order | None = None,
    ) -> bool:
        """Allow inline item changes only for editable orders.

        Args:
            request (HttpRequest): The current admin request.
            obj (Order | None): The parent order.

        Returns:
            bool: True when inline items may be changed.
        """
        return super().has_change_permission(
            request, obj
        ) and self._is_order_editable(obj)

    @override
    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: Order | None = None,
    ) -> bool:
        """Allow inline item deletion only for editable orders.

        Args:
            request (HttpRequest): The current admin request.
            obj (Order | None): The parent order.

        Returns:
            bool: True when inline items may be deleted.
        """
        return super().has_delete_permission(
            request, obj
        ) and self._is_order_editable(obj)

    @staticmethod
    def _is_order_editable(order: Order | None) -> bool:
        """Return whether an order can have its items edited.

        Args:
            order (Order | None): The order to check.

        Returns:
            bool: True when the order is not active.
        """
        return not is_order_active(order and order.pk)


class BaseOrderAdmin(admin.ModelAdmin):
    """Admin configuration for Order model."""

    list_display = (
        'id',
        'user',
        'state',
        'contact',
        'admin_total_sum',
        'created_at',
        'updated_at',
    )
    list_display_links = ('id', 'user')
    list_filter = ('state',)
    search_fields = ('id', f'user__{User.USERNAME_FIELD}')
    inlines = (OrderItemsInline,)
    save_on_top = True

    @override
    def get_queryset(self, request):
        """Annotate the order queryset with the total order value.

        Args:
            request (HttpRequest): The current admin request.

        Returns:
            QuerySet[Order]: Annotated queryset of orders.
        """
        qs = super().get_queryset(request)

        return qs.annotate(
            total_sum_value=Coalesce(
                Sum(F('items__shop_offer__price') * F('items__quantity')),
                0,
                output_field=IntegerField(),
            ),
        )

    @admin.display(
        description=_('Total sum'),
        ordering='total_sum_value',
    )
    def admin_total_sum(self, instance: Order) -> int:
        """Return the annotated total sum for the order."""
        return instance.total_sum_value


@admin.register(Basket)
class BasketAdmin(ExtraButtonsMixin, BaseOrderAdmin):
    """Admin configuration for Basket model."""

    form = BasketAdminForm
    readonly_fields_on_change = ('user',)

    @override
    def get_readonly_fields(
        self,
        request: HttpRequest,
        obj: Model | None = None,
    ) -> list[str] | tuple[str]:
        """Make basket owner read-only when editing an existing basket.

        Args:
            request (HttpRequest): The current admin request.
            obj (Model | None): The basket being edited, if any.

        Returns:
            list[str] | tuple[str]: Read-only field names for the
                current admin view.
        """
        result = list(super().get_readonly_fields(request, obj))
        if obj is not None:
            # Model change view
            result += self.readonly_fields_on_change
        return result

    @button(
        label=_('Checkout basket'),
        html_attrs={
            'class': 'button related-widget-wrapper-link',
            'style': 'background-color:#008000; color:var(--button-fg);',
            'data-popup': 'yes',
        },
    )
    def checkout(
        self: ExtraButtonsMixin,
        request: HttpRequest,
        object_id: object,
    ) -> HttpResponse:
        """Handle the admin checkout action for a basket.

        Args:
            self (ExtraButtonsMixin): The admin mixin instance.
            request (HttpRequest): The HTTP request.
            object_id (object): The basket's primary key.

        Returns:
            HttpResponse: Response for the checkout popup or form.
        """
        basket = get_object_or_404(Basket, pk=object_id)
        user = basket.user

        if request.method == 'POST':
            form = UserContactSelectForm(request.POST, user=user)
            if form.is_valid():
                contact: Contact = form.cleaned_data['contact']
                try:
                    checkout_basket(basket, contact, request)
                except Exception as e:
                    error_message(request, e)
                else:
                    messages.success(request, _('Order placed'))
                return TemplateResponse(request, 'api/close_popup.html')

        form = UserContactSelectForm(user=user)
        context = {
            **self.admin_site.each_context(request),
            'is_popup': True,
            'form': form,
            'basket': basket,
        }
        return TemplateResponse(request, 'api/checkout_basket.html', context)


@admin.register(PlacedOrder)
class OrderAdmin(DisableModelAddMixin, BaseOrderAdmin):
    """Admin configuration for PlacedOrder model."""

    form = OrderAdminForm
    readonly_fields = ('user',)

    @override
    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: PlacedOrder | None = None,
    ) -> bool:
        """Disable the delete permission for this admin model.

        Args:
            request (HttpRequest): The current admin request.
            obj (PlacedOrder | None): The order item being deleted.

        Returns:
            bool: Always False.
        """
        return False

    @override
    def save_model(
        self,
        request: HttpRequest,
        obj: PlacedOrder,
        form: ModelForm,
        change: bool,
    ) -> None:
        """Save an order and notify on committed state changes.

        Args:
            request (HttpRequest): The current admin request.
            obj (PlacedOrder): The placed order being saved.
            form (ModelForm): The submitted order form.
            change (bool): Whether an existing object is being changed.
        """
        state_changed = change and 'state' in form.changed_data
        if not state_changed:
            super().save_model(request, obj, form, change)
            return

        new_state: OrderState = obj.state

        # Restore old order state, the change must be done
        # by the service function
        old_state = get_order_state(obj.pk)
        obj.state = old_state

        with transaction.atomic():
            super().save_model(request, obj, form, change)
            try:
                change_order_state(obj, new_state, request)
            except Exception as e:
                error_message(request, e)
                transaction.rollback()
