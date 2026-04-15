from typing import Any, override
from urllib.parse import urlsplit

from django.conf import settings
from django.core.validators import URLValidator
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from .models import Contact
from .models import Shop
from .models import User


class PasswordField(serializers.CharField):
    """Password input field using hidden input rendering in forms."""

    def __init__(self, **kwargs):
        """Initialize password field styling."""
        super().__init__(
            style={'input_type': 'password'},
            **kwargs,
        )


class PositiveIntField(serializers.IntegerField):
    """Integer field that only accepts values greater than zero."""

    def __init__(self, **kwargs):
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
        """Validate the categories list contains unique IDs."""
        return self._validate_unique(value)

    def validate_goods(self, value: DictList) -> DictList:
        """Validate goods entries using unique part numbers."""
        return self._validate_unique(value, 'part_number')

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Validate goods -> category references."""
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
        """Ensure list items are unique by the given field."""
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
            parts = urlsplit(value or '')
            scheme = parts.scheme.lower()
            if scheme == 'file':
                return self._validate_file_url(parts)
            return super().__call__(value)

        def _validate_file_url(self, parts):
            """Validate a local file URL."""
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
        """Initialize URLField instance."""
        super().__init__(**kwargs)
        validator = URLValidator(message=self.error_messages['invalid'])
        self.validators.append(validator)


class ShopUpdateURLSerializer(serializers.Serializer):
    """Serializer for shop pricing update requests via URL."""

    url = URLField()


class ShopStateSerializer(serializers.ModelSerializer):
    """Serializer for Shop model."""

    state = serializers.BooleanField(source='is_active')

    class Meta:
        model = Shop
        fields = ('id', 'name', 'state')
        read_only_fields = ('id', 'name')
