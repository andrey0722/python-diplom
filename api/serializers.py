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
            'first_name',
            'last_name',
            'company',
            'position',
        )

    @override
    def create(self, validated_data: dict[str, Any]):
        password = validated_data.pop('password')
        instance: User = super().create(validated_data)
        instance.set_password(password)
        instance.save()
        return instance

    @override
    def update(self, instance: User, validated_data: dict[str, Any]):
        password = validated_data.pop('password', None)
        instance = super().update(instance, validated_data)
        if password is not None:
            instance.set_password(password)
            instance.save()
        return instance


class UserLoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(style={'input_type': 'password'})


class TokenSerializer(serializers.Serializer):
    token = serializers.CharField(source='key')
