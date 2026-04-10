from typing import Any, override

from rest_framework import serializers

from .models import User


class UserSerializer(serializers.ModelSerializer):
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


class SendEmailVerificationSerializer(EmailToUserSerializer): ...


class EmailConfirmSerializer(EmailToUserSerializer):
    token = serializers.CharField()


class UserLoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(style={'input_type': 'password'})


class TokenSerializer(serializers.Serializer):
    token = serializers.CharField(source='key')
