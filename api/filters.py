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

    class Meta:
        model = ShopOffer
        fields = ('shop_id', 'category_id')
