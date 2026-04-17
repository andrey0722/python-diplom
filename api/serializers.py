import json
import re
from typing import Any, override
from urllib.parse import urlsplit

from django.conf import settings
from django.core.validators import URLValidator
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from .models import Category
from .models import Contact
from .models import Order
from .models import OrderItem
from .models import Shop
from .models import ShopOffer
from .models import User


class PasswordField(serializers.CharField):
    """Password input field using hidden input rendering in forms."""

    def __init__(self, **kwargs):
        """Initialize password field with secure input styling.

        Args:
            kwargs: Additional arguments passed to CharField.
        """
        super().__init__(style={'input_type': 'password'}, **kwargs)


class PositiveIntField(serializers.IntegerField):
    """Integer field that only accepts values greater than zero."""

    def __init__(self, **kwargs):
        """Initialize the positive integer field with minimum value of 1.

        Args:
            **kwargs: Additional arguments passed to IntegerField.
        """
        super().__init__(min_value=1, **kwargs)


class UserSerializer(serializers.ModelSerializer):
    """Serializer for User model with password handling."""

    password = PasswordField(write_only=True)

    class Meta:
        model = User
        fields = (
            'id',
            'email',
            'password',
            'is_active',
            'first_name',
            'last_name',
            'company',
            'position',
        )
        read_only_fields = [
            'id',
            'is_active',
        ]

    @override
    def create(self, validated_data: dict[str, Any]):
        """Create user and hash a password.

        Args:
            validated_data (dict[str, Any]): The validated data.

        Returns:
            User: The created user instance.
        """
        password = validated_data.pop('password')
        instance: User = super().create(validated_data)
        instance.set_password(password)
        instance.is_active = False  # Need to validate email first
        instance.save()
        return instance

    @override
    def update(self, instance: User, validated_data: dict[str, Any]):
        """Update user and password if provided.

        Args:
            instance (User): The user instance to update.
            validated_data (dict[str, Any]): The validated data.

        Returns:
            User: The updated user instance.
        """
        password = validated_data.pop('password', None)
        instance = super().update(instance, validated_data)
        if password is not None:
            instance.set_password(password)
            instance.save()
        return instance


class VerificationSentSerializer(serializers.Serializer):
    """Serializer for verification email sent response."""

    status = serializers.CharField()


if settings.DEBUG:

    class DebugVerificationSentSerializer(VerificationSentSerializer):
        """Add the token itself in DEBUG mode only."""

        token = serializers.CharField()

    VerificationSentSerializer = DebugVerificationSentSerializer


class EmailToUserSerializer(serializers.Serializer):
    """Serializer for email input with user lookup."""

    email = serializers.EmailField()

    @override
    def validate(self, attrs):
        """Validate email and retrieve user.

        Args:
            attrs (dict): The input attributes.

        Returns:
            dict: The validated attributes with user object if found.
        """
        email = attrs['email']
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            user = None
        attrs['user'] = user
        return attrs


class SendEmailVerificationSerializer(EmailToUserSerializer):
    """Serializer for sending email verification."""


class EmailConfirmSerializer(EmailToUserSerializer):
    """Serializer for email confirmation with token."""

    token = serializers.CharField()


class SendPasswordResetSerializer(EmailToUserSerializer):
    """Serializer for sending password reset emails."""


class PasswordResetConfirmSerializer(EmailToUserSerializer):
    """Serializer for confirming password reset using a token."""

    password = PasswordField()
    token = serializers.CharField()


class UserLoginSerializer(serializers.Serializer):
    """Serializer for user login credentials."""

    email = serializers.EmailField()
    password = serializers.CharField(style={'input_type': 'password'})


class TokenSerializer(serializers.Serializer):
    """Serializer for token response."""

    token = serializers.CharField(source='key')


class ContactSerializer(serializers.ModelSerializer):
    """Serializer for Contact model."""

    class Meta:
        model = Contact
        fields = (
            'id',
            'first_name',
            'middle_name',
            'last_name',
            'email',
            'phone',
            'city',
            'street',
            'house',
            'structure',
            'building',
            'apartment',
        )
        read_only_fields = ('id',)


class IdSerializer(serializers.Serializer):
    """Serializer for single ID input."""

    id = serializers.IntegerField()


class ItemsSerializer(serializers.Serializer):
    """Serializer for comma-separated list of item IDs."""

    items = serializers.CharField(required=False, default='')

    def validate_items(self, value: str) -> list[int]:
        """Validate a comma-separated list of item IDs.

        Args:
            value (str): Comma-separated item IDs.

        Returns:
            list[int]: Parsed item IDs.
        """
        parts = [part.strip() for part in value.split(',')]
        try:
            result = [int(part) for part in parts if part]
        except ValueError:
            raise serializers.ValidationError(_('All items must be integers.'))
        if not result:
            raise serializers.ValidationError(_('Empty number list.'))
        return result


class PricingCategorySerializer(serializers.Serializer):
    """Serializer for product category entries in shop pricing payloads."""

    id = PositiveIntField()
    name = serializers.CharField()


class PricingProductSerializer(serializers.Serializer):
    """Serializer for products listed in shop pricing uploads."""

    id = PositiveIntField(source='part_number')
    category = PositiveIntField()
    model = serializers.CharField()
    name = serializers.CharField()
    price = PositiveIntField()
    price_rrc = PositiveIntField(source='msrp')
    quantity = PositiveIntField()
    parameters = serializers.DictField()


class ShopPricingSerializer(serializers.Serializer):
    """Serializer for shop pricing documents submitted by shop owners."""

    shop = serializers.CharField()
    categories = serializers.ListField(child=PricingCategorySerializer())
    goods = serializers.ListField(child=PricingProductSerializer())

    type DictList = list[dict[str, object]]

    def validate_categories(self, value: DictList) -> DictList:
        """Validate the categories list contains unique IDs.

        Args:
            value (DictList): List of category dictionaries.

        Returns:
            DictList: The validated categories list.
        """
        return self._validate_unique(value)

    def validate_goods(self, value: DictList) -> DictList:
        """Validate goods entries using unique part numbers.

        Args:
            value (DictList): List of product dictionaries.

        Returns:
            DictList: The validated goods list.
        """
        return self._validate_unique(value, 'part_number')

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Validate goods -> category references to ensure integrity.

        Args:
            attrs (dict[str, Any]): The attributes being validated.

        Returns:
            dict[str, Any]: The validated attributes.

        Raises:
            ValidationError: If any product references invalid category.
        """
        goods_errors = {}
        category_ids = {category['id'] for category in attrs['categories']}

        for index, product in enumerate(attrs['goods']):
            item_errors = {}
            category_id = product['category']

            if category_id not in category_ids:
                item_errors['category'] = {
                    'error': _('Invalid category reference'),
                    'value': category_id,
                }

            if item_errors:
                goods_errors[index] = item_errors

        if goods_errors:
            raise serializers.ValidationError({'goods': goods_errors})
        return super().validate(attrs)

    @staticmethod
    def _validate_unique(value: DictList, field_name: str = 'id') -> DictList:
        """Ensure list items are unique by the given field.

        Args:
            value (DictList): List of dictionaries to validate.
            field_name (str): Field name to check for duplicates.

        Returns:
            DictList: The validated list.

        Raises:
            ValidationError: If duplicate values are found.
        """
        found_ids = set()
        errors = {}

        for index, item in enumerate(value):
            item_errors = {}
            item_id = item[field_name]

            if item_id in found_ids:
                item_errors[field_name] = {
                    'error': _('Duplicate item id'),
                    'value': item_id,
                }

            found_ids.add(item_id)

            if item_errors:
                errors[index] = item_errors

        if errors:
            raise serializers.ValidationError(errors)
        return value


if settings.DEBUG:

    class DebugURLValidator(URLValidator):
        """URL validator that accepts also local file URLs."""

        @override
        def __call__(self, value: str | None) -> None:
            """Validate a URL, allowing local file URLs in debug mode.

            Args:
                value (str | None): The URL string to validate.

            Raises:
                ValidationError: If the URL is invalid.
            """
            parts = urlsplit(value or '')
            scheme = parts.scheme.lower()
            if scheme == 'file':
                return self._validate_file_url(parts)
            return super().__call__(value)

        def _validate_file_url(self, parts):
            """Validate a local file URL.

            Args:
                parts: URL components from urlsplit.

            Raises:
                ValidationError: If the file URL is invalid.
            """
            if parts.netloc or not parts.path:
                # pass
                raise serializers.ValidationError(self.message)

    URLValidator = DebugURLValidator


class URLField(serializers.CharField):
    """Validates input URL strings."""

    default_error_messages = {
        'invalid': _('Enter a valid URL.'),
    }

    def __init__(self, **kwargs):
        """Initialize URLField with URL validator.

        Args:
            kwargs: Additional arguments passed to CharField.
        """
        super().__init__(**kwargs)
        validator = URLValidator(message=self.error_messages['invalid'])
        self.validators.append(validator)


class ShopUpdateURLSerializer(serializers.Serializer):
    """Serializer for shop pricing update requests via URL."""

    url = URLField()


class ShopSerializer(serializers.ModelSerializer):
    """Serializer for Shop model."""

    state = serializers.BooleanField(source='is_active')

    class Meta:
        model = Shop
        fields = ('id', 'name', 'state')
        read_only_fields = ('id', 'name')


class CategorySerializer(serializers.ModelSerializer):
    """Serializer for Category model."""

    class Meta:
        model = Category
        fields = ('id', 'name')
        read_only_fields = ('id', 'name')


class ShopOfferSerializer(serializers.ModelSerializer):
    """Serializer for ShopOffer model."""

    name = serializers.CharField(source='product.name')
    category = CategorySerializer(source='product.category')
    price_rrc = PositiveIntField(source='msrp')
    shop = ShopSerializer()

    class Meta:
        model = ShopOffer
        fields = (
            'id',
            'name',
            'model',
            'quantity',
            'price',
            'price_rrc',
            'discount',
            'category',
            'shop',
        )


class JsonListField(serializers.ListField):
    """Custom list field that parses JSON strings into Python lists.

    Handles JSON strings with optional trailing commas and converts them
    to Python list objects.
    """

    default_error_messages = {
        'invalid_json': _('Invalid JSON string: {reason}'),
    }

    text_preprocess = (
        (re.compile(r',\s*[\]]'), ']'),
        (re.compile(r',\s*[}]'), '}'),
    )
    """Remove trailing commas from input."""

    @override
    def get_value(self, dictionary: dict) -> Any:
        """Get value from dictionary, supporting partial updates.

        Args:
            dictionary (dict): The input data dictionary.

        Returns:
            Any: The field value or empty if not present in partial update.
        """
        if self.field_name not in dictionary:
            partial = getattr(self.root, 'partial', False)
            if partial:
                return serializers.empty
        return dictionary.get(self.field_name, serializers.empty)

    @override
    def to_internal_value(self, data: Any) -> list[Any]:
        """Convert JSON string or list to internal list representation.

        Preprocesses the data to remove trailing commas and parses JSON strings.

        Args:
            data (Any): The input data (JSON string or list).

        Returns:
            list[Any]: The processed list of items.

        Raises:
            ValidationError: If JSON parsing fails or data is not a list.
        """
        if isinstance(data, str):
            # Preprocess data
            for pattern, replace in self.text_preprocess:
                data = re.sub(pattern, replace, data)
            # Parse as JSON list
            try:
                data = json.loads(data)
            except json.JSONDecodeError as e:
                self.fail('invalid_json', reason=str(e))

        if not isinstance(data, list):
            self.fail('not_a_list', input_type=type(data).__name__)
        return super().to_internal_value(data)


class AddToBasketItemSerializer(serializers.ModelSerializer):
    """Serializer for individual items being added to the basket."""

    product_info = serializers.IntegerField(source='shop_offer_id')

    class Meta:
        model = OrderItem
        fields = ('product_info', 'quantity')


class AddToBasketSerializer(serializers.Serializer):
    """Serializer for adding multiple items to the basket."""

    items = JsonListField(child=AddToBasketItemSerializer())


class EditBasketItemSerializer(serializers.ModelSerializer):
    """Serializer for basket items being edited with new quantities."""

    id = serializers.IntegerField()

    class Meta:
        model = OrderItem
        fields = ('id', 'quantity')


class EditBasketSerializer(serializers.Serializer):
    """Serializer for updating multiple items in the basket."""

    items = JsonListField(child=EditBasketItemSerializer())


class OrderItemSerializer(serializers.ModelSerializer):
    """Serializer for order items displayed in order details."""

    product_info = serializers.IntegerField(source='shop_offer_id')

    class Meta:
        model = OrderItem
        fields = ('id', 'product_info', 'quantity')
        read_only_fields = ('id',)


class OrderSerializer(serializers.ModelSerializer):
    """Serializer for Order model with nested items."""

    items = OrderItemSerializer(many=True)

    class Meta:
        model = Order
        fields = ('id', 'state', 'items')
        read_only_fields = ('id', 'state')
