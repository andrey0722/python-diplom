from typing import Any, NoReturn, override

from admin_extra_buttons.decorators import button
from admin_extra_buttons.mixins import ExtraButtonsMixin
from django.contrib import admin
from django.contrib import messages
from django.contrib.admin.options import BaseModelAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Case
from django.db.models import Count
from django.db.models import F
from django.db.models import IntegerField
from django.db.models import Model
from django.db.models import Prefetch
from django.db.models import QuerySet
from django.db.models import Sum
from django.db.models import Value
from django.db.models import When
from django.db.models.fields.related import RelatedField
from django.db.models.functions import Cast
from django.db.models.functions import Coalesce
from django.db.models.functions import Floor
from django.forms import ModelForm
from django.http import HttpRequest
from django.http import HttpResponse
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.html import format_html
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
from .templates import get_order_context
from .templates import get_order_items_context


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


class OptimizeFieldsQueriesMixin(BaseModelAdmin):
    """Admin mixin that optimizes related field querysets."""

    @override
    def get_field_queryset(
        self,
        db: str | None,
        db_field: RelatedField,
        request: HttpRequest,
    ) -> QuerySet | None:
        """Return an optimized queryset for selected related fields.

        Args:
            db (str | None): Database alias for the field queryset.
            db_field (RelatedField): Related field being rendered.
            request (HttpRequest): The current admin request.

        Returns:
            QuerySet | None: Optimized field queryset when available.
        """
        queryset = super().get_field_queryset(db, db_field, request)
        if queryset is None:
            queryset = self._get_initial_queryset(db_field.name)
        if queryset is not None:
            queryset = self._prefetch_queryset(db_field.name, queryset)
        return queryset

    @staticmethod
    def _get_initial_queryset(field_name: str) -> QuerySet | None:
        """Return the base queryset for an optimized field.

        Args:
            field_name (str): Related field name.

        Returns:
            QuerySet | None: Base queryset for known fields.
        """
        match field_name:
            case 'order':
                manager = Order.objects
            case 'product':
                manager = Product.objects
            case 'shop_offer':
                manager = ShopOffer.objects
            case _:
                return None
        return manager.get_queryset()

    @staticmethod
    def _prefetch_queryset(field_name: str, queryset: QuerySet) -> QuerySet:
        """Apply field-specific queryset optimizations.

        Args:
            field_name (str): Related field name.
            queryset (QuerySet): Base queryset to optimize.

        Returns:
            QuerySet: Optimized queryset for the field.
        """
        match field_name:
            case 'order':
                return queryset.only(
                    'id', 'state', 'user__email'
                ).select_related('user', 'contact')
            case 'product':
                return queryset.only('id', 'name')
            case 'shop_offer':
                return queryset.only(
                    'id', 'price', 'shop__name', 'product__name'
                ).select_related('shop', 'product')
        return queryset


class ReadonlyFieldsChangeViewMixin(BaseModelAdmin):
    """Admin mixin that adds read-only fields on change views."""

    readonly_fields_change_view = ()

    @override
    def get_readonly_fields(
        self,
        request: HttpRequest,
        obj: Model | None = None,
    ) -> list[str] | tuple[str]:
        """Return read-only fields for add or change views.

        Args:
            request (HttpRequest): The current admin request.
            obj (Model | None): Object being edited, if any.

        Returns:
            list[str] | tuple[str]: Read-only field names.
        """
        fields = list(super().get_readonly_fields(request, obj))
        if obj is not None:
            # Model change view
            fields += self.readonly_fields_change_view
        return fields


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
    ) -> NoReturn:
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
    show_change_link = True

    @override
    def get_queryset(self, request: HttpRequest) -> QuerySet:
        """Return contacts with users selected for inline display.

        Args:
            request (HttpRequest): The current admin request.

        Returns:
            QuerySet: Contact queryset with related user loaded.
        """
        return super().get_queryset(request).select_related('user')


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
    search_fields = ('email', 'first_name', 'last_name')
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
    add_fieldsets = (
        (
            None,
            {
                'classes': ('wide',),
                'fields': (
                    'email',
                    'usable_password',
                    'password1',
                    'password2',
                ),
            },
        ),
    )
    ordering = ('pk',)
    inlines = (ContactsInline,)
    save_on_top = True


@admin.register(Token)
class TokenAdmin(ReadonlyFieldsChangeViewMixin, admin.ModelAdmin):
    """Admin configuration for Token model."""

    list_display = ('key', 'user', 'created')
    list_filter = ('created',)
    search_fields = ('user__email',)
    search_help_text = _('User')
    readonly_fields_change_view = ('user',)
    autocomplete_fields = ('user',)


@admin.register(Contact)
class ContactAdmin(ReadonlyFieldsChangeViewMixin, admin.ModelAdmin):
    """Admin configuration for Contact model."""

    list_display = (
        'address',
        'user',
        'contact_person',
        'contact_email',
        'phone',
    )
    list_filter = ('city', 'user')
    list_select_related = ('user',)
    search_fields = (
        'user__email',
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
    autocomplete_fields = ('user',)
    readonly_fields_change_view = ('user',)
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
    show_change_link = True


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    """Admin configuration for Category model."""

    list_display = ('name', 'products_count')
    search_fields = ('name',)
    inlines = (ProductsInline,)
    save_on_top = True

    @override
    def get_queryset(self, request: HttpRequest) -> QuerySet:
        """Annotate categories with product counts for admin display.

        Args:
            request (HttpRequest): The current admin request.

        Returns:
            QuerySet: Category queryset annotated with product counts.
        """
        return (
            super()
            .get_queryset(request)
            .annotate(products_count_value=Count('products'))
        )

    @admin.display(
        description=_('Products count'),
        ordering='products_count_value',
    )
    def products_count(self, obj: Category) -> int:
        """Return the annotated product count for a category.

        Args:
            obj (Category): The category displayed in admin.

        Returns:
            int: Annotated product count value.
        """
        return obj.products_count_value


class OffersInline(  # pyright: ignore[reportIncompatibleMethodOverride]
    OptimizeFieldsQueriesMixin,
    ReadonlyFieldsChangeViewMixin,
    admin.StackedInline,
):
    """Inline admin for ShopOffer model."""

    model = ShopOffer
    autocomplete_fields = ('product', 'shop')
    readonly_fields_change_view = ('shop',)
    extra = 0
    show_change_link = True

    @override
    def get_queryset(self, request: HttpRequest) -> QuerySet:
        """Return shop offers with related shop and product loaded.

        Args:
            request (HttpRequest): The current admin request.

        Returns:
            QuerySet: Shop offer queryset with related objects loaded.
        """
        return super().get_queryset(request).select_related('shop', 'product')


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    """Admin configuration for Product model."""

    list_display = ('name', 'category', 'offers_count')
    search_fields = ('name',)
    autocomplete_fields = ('category',)
    inlines = (OffersInline,)
    save_on_top = True

    @override
    def get_queryset(self, request: HttpRequest) -> QuerySet:
        """Annotate products with offer counts for admin display.

        Args:
            request (HttpRequest): The current admin request.

        Returns:
            QuerySet: Product queryset annotated with offer counts.
        """
        return (
            super()
            .get_queryset(request)
            .only('name', 'category__name')
            .select_related('category')
            .annotate(offers_count_value=Count('offers'))
        )

    @admin.display(
        description=_('Offers count'),
        ordering='offers_count_value',
    )
    def offers_count(self, obj: Product) -> int:
        """Return the annotated offer count for a product.

        Args:
            obj (Product): The product displayed in admin.

        Returns:
            int: Annotated offer count value.
        """
        return obj.offers_count_value


@admin.register(Shop)
class ShopAdmin(ReadonlyFieldsChangeViewMixin, admin.ModelAdmin):
    """Admin configuration for Shop model."""

    list_display = ('name', 'user', 'offers_count', 'is_active')
    list_filter = ('is_active',)
    list_editable = ('is_active',)
    search_fields = ('name', 'user__email')
    autocomplete_fields = ('user',)
    readonly_fields_change_view = ('user',)
    inlines = (OffersInline,)
    save_on_top = True

    @override
    def get_queryset(self, request: HttpRequest) -> QuerySet:
        """Return shops with offer counts and users for admin display.

        Args:
            request (HttpRequest): The current admin request.

        Returns:
            QuerySet: Shop queryset annotated with offer counts.
        """
        return (
            super()
            .get_queryset(request)
            .only('name', 'is_active', 'user__email')
            .select_related('user')
            .annotate(offers_count_value=Count('offers'))
        )

    @admin.display(
        description=_('Offers count'),
        ordering='offers_count_value',
    )
    def offers_count(self, obj: Shop) -> int:
        """Return the annotated offer count for a shop.

        Args:
            obj (Shop): The shop displayed in admin.

        Returns:
            int: Annotated offer count value.
        """
        return obj.offers_count_value


@admin.register(Parameter)
class ParameterAdmin(admin.ModelAdmin):
    """Admin configuration for Parameter model."""

    list_display = ('name',)
    search_fields = ('name',)


class ProductParametersInline(admin.TabularInline):
    """Inline admin for ProductParameter model."""

    model = ProductParameter
    autocomplete_fields = ('parameter',)
    extra = 0
    show_change_link = True


@admin.register(ShopOffer)
class ShopOfferAdmin(ReadonlyFieldsChangeViewMixin, admin.ModelAdmin):
    """Admin configuration for ShopOffer model."""

    list_display = (
        'id',
        'product',
        'shop',
        'part_number',
        'price',
        'admin_discount',
        'quantity',
        'is_active',
    )
    list_display_links = ('id', 'product')
    list_select_related = ('shop', 'product')
    list_filter = ('shop__name',)
    search_fields = ('id', 'shop__name', 'product__name', 'part_number')
    autocomplete_fields = ('product', 'shop')
    readonly_fields_change_view = ('shop',)
    inlines = (ProductParametersInline,)
    save_on_top = True

    @override
    def get_queryset(self, request: HttpRequest) -> QuerySet:
        """Annotate shop offers with discount values for admin display.

        Args:
            request (HttpRequest): The current admin request.

        Returns:
            QuerySet: Shop offer queryset annotated with discounts.
        """
        return (
            super()
            .get_queryset(request)
            .annotate(
                discount_value=Case(
                    When(
                        msrp__gt=0,
                        then=Cast(
                            Floor(
                                (F('msrp') - F('price')) * 100.0 / F('msrp')
                            ),
                            output_field=IntegerField(),
                        ),
                    ),
                    default=Value(0),
                    output_field=IntegerField(),
                ),
            )
        )

    @admin.display(description=_('Discount, %'), ordering='discount_value')
    def admin_discount(self, obj: ShopOffer) -> int:
        """Return the annotated discount value for a shop offer.

        Args:
            obj (ShopOffer): The shop offer displayed in admin.

        Returns:
            int: Annotated discount value.
        """
        return obj.discount_value


@admin.register(OrderItem)
class OrderItemAdmin(
    OptimizeFieldsQueriesMixin,
    DisableModelAddMixin,
    admin.ModelAdmin,
):
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
    list_display_links = ('id', 'order')
    list_select_related = (
        'order__user',
        'shop_offer__product',
        'shop_offer__shop',
    )
    list_filter = ('order__state', 'shop_offer__shop__name')
    search_fields = ('id', 'order__id', 'order__user__email')
    fields = ('order_admin_link', 'shop_offer', 'quantity')
    readonly_fields = ('order_admin_link',)
    save_on_top = True

    @admin.display(description=_('Order'))
    def order_admin_link(self, obj: OrderItem) -> str:
        """Return a link to the related order admin page.

        Args:
            obj (OrderItem): The order item displayed in admin.

        Returns:
            str: HTML link to the related order.
        """
        if obj.order_id is None:
            return '-'
        proxy_model = obj.order.proxy_model
        url = get_admin_view(proxy_model, 'change', obj.order_id)
        return format_html('<a href="{}">{}</a>', url, obj.order)

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
        return item is None or item.order.state in OrderState.inactive()


class OrderItemsInline(OptimizeFieldsQueriesMixin, admin.StackedInline):
    """Inline admin for OrderItem model."""

    model = OrderItem
    formset = OrderItemInlineFormSet
    autocomplete_fields = ('shop_offer',)
    extra = 0
    show_change_link = True

    @override
    def get_queryset(self, request: HttpRequest) -> QuerySet:
        """Return order items with related order and offer data loaded.

        Args:
            request (HttpRequest): The current admin request.

        Returns:
            QuerySet: Order item queryset with related objects loaded.
        """
        return (
            super()
            .get_queryset(request)
            .only(
                'id',
                'quantity',
                'order__state',
                'order__user__email',
                'shop_offer__price',
                'shop_offer__shop__name',
                'shop_offer__product__name',
            )
            .select_related(
                'order__user',
                'shop_offer__shop',
                'shop_offer__product',
            )
        )

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
        return order is None or order.state in OrderState.inactive()


class BaseOrderAdmin(admin.ModelAdmin):
    """Admin configuration for Order model."""

    list_display = (
        'id',
        'user',
        'state',
        'items_count',
        'admin_total_sum',
        'contact',
        'created_at',
        'updated_at',
    )
    list_display_links = ('id', 'user')
    list_filter = ('state',)
    search_fields = ('id', 'user__email')
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
        return (
            super()
            .get_queryset(request)
            .only(
                'id',
                'state',
                'created_at',
                'updated_at',
                'user__email',
                'contact',
            )
            .select_related('user', 'contact', 'contact__user')
            .annotate(
                items_count=Count('items'),
                total_sum_value=Coalesce(
                    Sum(F('items__shop_offer__price') * F('items__quantity')),
                    0,
                    output_field=IntegerField(),
                ),
            )
        )

    @admin.display(
        description=_('Items'),
        ordering='items_count',
    )
    def items_count(self, instance: Order) -> int:
        """Return the annotated item count for the order.

        Args:
            instance (Order): The order displayed in admin.

        Returns:
            int: Annotated item count.
        """
        return instance.items_count

    @admin.display(
        description=_('Total sum'),
        ordering='total_sum_value',
    )
    def admin_total_sum(self, instance: Order) -> int:
        """Return the annotated total sum for the order.

        Args:
            instance (Order): The order displayed in admin.

        Returns:
            int: Annotated total sum.
        """
        return instance.total_sum_value


@admin.register(Basket)
class BasketAdmin(
    ExtraButtonsMixin,
    ReadonlyFieldsChangeViewMixin,
    BaseOrderAdmin,
):
    """Admin configuration for Basket model."""

    form = BasketAdminForm
    autocomplete_fields = ('user',)
    readonly_fields_change_view = ('user',)

    basket_template = 'api/checkout_basket.html'
    close_template = 'api/close_popup.html'

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
        items = Prefetch(
            'items',
            OrderItem.objects.only(
                'pk',
                'order_id',
                'quantity',
                'shop_offer__part_number',
                'shop_offer__model',
                'shop_offer__price',
                'shop_offer__product__name',
            ).select_related('shop_offer__product'),
        )
        basket = Basket.objects.prefetch_related(items).get(pk=object_id)
        user = basket.user

        if request.method == 'POST':
            form = UserContactSelectForm(request.POST, user=user)
            if form.is_valid():
                contact: Contact = form.cleaned_data['contact']
                context = None
                try:
                    order = checkout_basket(basket, contact, request)
                except Exception as e:
                    error_message(request, e)
                else:
                    messages.success(request, _('Order placed'))
                    context = {
                        'redirect_url': get_admin_view(
                            PlacedOrder,
                            'change',
                            order.pk,
                        ),
                    }
                close_template = getattr(self, 'close_template', '')
                return TemplateResponse(request, close_template, context)
        else:
            form = UserContactSelectForm(user=user)

        context = {
            **self.admin_site.each_context(request),
            'is_popup': True,
            'form': form,
        }
        items = list(basket.items.all())
        order_context = get_order_context(request, basket)
        context.update(get_order_items_context(items, order_context))
        basket_template = getattr(self, 'basket_template', '')
        return TemplateResponse(request, basket_template, dict(context))


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
                change_order_state(obj, new_state, None, request)
            except Exception as e:
                error_message(request, e)
                transaction.rollback()
