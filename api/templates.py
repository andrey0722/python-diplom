from collections.abc import Iterable
from collections.abc import Iterator
from typing import Final, TypedDict, cast

from django.contrib.sites.shortcuts import get_current_site
from django.db.models import Prefetch
from django.http import HttpRequest
from django.urls import reverse
from rest_framework.request import Request

from .models import Order
from .models import OrderItem
from .models import OrderState
from .models import Shop
from .models import ShopOffer

type AnyRequest = HttpRequest | Request


class RequestContext(TypedDict):
    """Context shared by email templates that build absolute links."""

    domain: str
    site_name: str
    protocol: str


class VerifyContext(RequestContext):
    """Context for email templates that confirm token-based requests."""

    token: str
    request_type: str
    request_url: str
    request_data: str


class OrderContext(RequestContext):
    """Context shared by order notification email templates."""

    order_id: object
    order_state: str
    user_order_url: str
    shop_order_url: str


class OrderItemsContext(OrderContext):
    """Context for order email templates that render order items."""

    items: list[dict[str, str | int]]
    total_sum: int


class UserOrderContext(OrderItemsContext):
    """Context for order email templates sent to customers."""


class ShopOrderContext(OrderItemsContext):
    """Context for order email templates sent to shop admins."""

    shop_name: str


def get_request_context(request: AnyRequest) -> RequestContext:
    """Build the base context used for email message templates.

    Args:
        request (AnyRequest): The request object.

    Returns:
        RequestContext: Context dictionary for the template.
    """
    if isinstance(request, Request):
        # `Request` works as a proxy over `HttpRequest`
        request = cast(HttpRequest, request)

    current_site = get_current_site(request)
    return RequestContext(
        domain=current_site.domain,
        site_name=current_site.name,
        protocol='https' if request.is_secure() else 'http',
    )


def _construct_url(
    request: AnyRequest,
    view_name: str,
    **kwargs: object,
) -> str:
    path = reverse(view_name, kwargs=kwargs)
    return request.build_absolute_uri(path)


def get_verify_context(
    request: AnyRequest,
    token: str,
    view_name: str,
    request_type: str,
    request_data: str,
) -> VerifyContext:
    """Build email context for token verification requests.

    Args:
        request (AnyRequest): The request used to build absolute URLs.
        token (str): Verification token included in the email.
        view_name (str): URL name for the verification endpoint.
        request_type (str): HTTP method shown in the email.
        request_data (str): Payload included in the email instructions.

    Returns:
        VerifyContext: Context data for verification email templates.
    """
    request_url = _construct_url(request, view_name)
    request_context = get_request_context(request)
    return VerifyContext(
        token=token,
        request_type=request_type,
        request_url=request_url,
        request_data=request_data,
        **request_context,
    )


def get_order_context(
    request: AnyRequest,
    order: Order,
) -> OrderContext:
    """Build shared order notification context.

    Args:
        request (AnyRequest): The request used to build absolute URLs.
        order (Order): Order included in the notification.

    Returns:
        OrderContext: Context data shared by order email templates.
    """
    request_context = get_request_context(request)
    return OrderContext(
        order_id=order.pk,
        order_state=str(OrderState(order.state).label),
        user_order_url=_construct_url(request, 'order', pk=order.pk),
        shop_order_url=_construct_url(request, 'shop-order', pk=order.pk),
        **request_context,
    )


_ORDER_ITEM_TEMPLATE_ATTRS: Final = (
    'pk',
    'product_name',
    'quantity',
    'price',
    'sum',
    'part_number',
    'model',
)


def get_order_items_context(
    items: Iterable[OrderItem],
    order_context: OrderContext,
) -> OrderItemsContext:
    """Build order item context and total sum for email templates.

    Args:
        items (Iterable[OrderItem]): Order items to include.
        order_context (OrderContext): Shared order context.

    Returns:
        OrderItemsContext: Context data with rendered item values.
    """
    total_sum = 0
    template_items = []
    for item in items:
        total_sum += item.sum
        template_items.append(
            {attr: getattr(item, attr) for attr in _ORDER_ITEM_TEMPLATE_ATTRS}
        )

    return OrderItemsContext(
        items=template_items,
        total_sum=total_sum,
        **order_context,
    )


def get_order_user_context(
    order: Order,
    order_context: OrderContext,
) -> UserOrderContext:
    """Build order notification context for a customer.

    Args:
        order (Order): Order whose items are included.
        order_context (OrderContext): Shared order context.

    Returns:
        UserOrderContext: Context data for customer order emails.
    """
    items = list(order.items.all())
    items_context = get_order_items_context(items, order_context)
    return UserOrderContext(**items_context)


def get_shop_context(
    shop: Shop,
    order_context: OrderContext,
) -> ShopOrderContext:
    """Build order notification context for a shop admin.

    Args:
        shop (Shop): Shop with prefetched offers and order items.
        order_context (OrderContext): Shared order context.

    Returns:
        ShopOrderContext: Context data for shop admin order emails.
    """
    items = [
        item
        for offer in shop.offers_for_order
        for item in offer.order_items_for_order
    ]
    items_context = get_order_items_context(items, order_context)
    return ShopOrderContext(shop_name=shop.name, **items_context)


def _prefetch_shops_with_items(order: Order) -> list[Shop]:
    order_items = Prefetch(
        'order_items',
        queryset=OrderItem.objects.select_related(
            'shop_offer',
            'shop_offer__product',
        )
        .select_for_update()
        .filter(order_id=order.pk),
        to_attr='order_items_for_order',
    )
    offers = Prefetch(
        'offers',
        queryset=ShopOffer.objects.select_for_update()
        .filter(order_items__order_id=order.pk)
        .prefetch_related(
            order_items,
        ),
        to_attr='offers_for_order',
    )
    queryset = (
        Shop.objects.filter(offers__order_items__order_id=order.pk)
        .select_for_update()
        .select_related('user')
        .prefetch_related(offers)
        .all()
    )

    # Return unique shops
    shops = list(queryset)
    shop_dict = {shop.pk: shop for shop in shops}
    return list(shop_dict.values())


def get_shops_and_context(
    order: Order,
    order_context: OrderContext,
) -> Iterator[tuple[Shop, ShopOrderContext]]:
    """Yield each shop and its order notification context.

    Args:
        order (Order): Order used to load participating shops.
        order_context (OrderContext): Shared order context.

    Yields:
        tuple[Shop, ShopOrderContext]: Shop and matching email context.
    """
    shops = _prefetch_shops_with_items(order)
    for shop in shops:
        context = get_shop_context(shop, order_context)
        yield shop, context
