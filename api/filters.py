from django.db.models import Q
from django.db.models import QuerySet
from django.utils.translation import gettext_lazy as _
from django_filters import rest_framework as filters

from .models import Category
from .models import Shop
from .models import ShopOffer


class ShopFilter(filters.FilterSet):
    """Filter set for searching shops by name."""

    name = filters.CharFilter(lookup_expr='icontains')

    class Meta:
        model = Shop
        fields = ('name',)


class CategoryFilter(filters.FilterSet):
    """Filter set for searching categories by name."""

    name = filters.CharFilter(lookup_expr='icontains')

    class Meta:
        model = Category
        fields = ('name',)


class ShopOfferFilter(filters.FilterSet):
    """Filter set for shop offers by category and shop."""

    category_id = filters.NumberFilter(field_name='product__category__id')
    shop_id = filters.NumberFilter(field_name='shop__id')
    shop_active = filters.BooleanFilter(field_name='shop__is_active')
    part_number = filters.NumberFilter()
    search = filters.CharFilter(method='text_search', label=_('Text search'))

    class Meta:
        model = ShopOffer
        fields = ('shop_id', 'category_id', 'part_number')

    def text_search(
        self,
        queryset: QuerySet,
        _field_name: str,
        value: object,
    ) -> QuerySet:
        """
        Filter shop offers by text search across product name and model.

        Performs case-insensitive text search against both the related
        product's name and the shop offer's model field, returning any
        offers that match either criterion.

        Args:
            queryset (QuerySet): The initial queryset of ShopOffer objects.
            _field_name: The field name (unused, required by FilterSet).
            value: The search string to match against product name and model.

        Returns:
            QuerySet: A filtered QuerySet matching the search criteria.
        """
        return queryset.filter(
            Q(product__name__icontains=value) | Q(model__icontains=value)
        )
