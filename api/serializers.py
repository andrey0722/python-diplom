from typing import Any, override

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from .models import Contact
from .models import User


class UserSerializer(serializers.ModelSerializer):
    """Serializer for User model with password handling."""

    password = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'},
    )

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
