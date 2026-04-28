from typing import Any, cast, override

from rest_framework.permissions import BasePermission
from rest_framework.request import Request

from .models import AnyUser
from .models import Shop
from .models import User


class UserOwnsShop(BasePermission):
    """Permission that requires the user to own a shop."""

    @override
    def has_permission(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        request: Request,
        view: object,
    ) -> bool:
        """Allow access only to users with a shop.

        Args:
            request (Request): The current request.
            view (object): The view requesting permission.

        Returns:
            bool: True when the authenticated user owns a shop.
        """
        user = cast(AnyUser, request.user)
        if isinstance(user, User):
            return Shop.objects.filter(user_id=user.pk).exists()
        return False

    @override
    def has_object_permission(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        request: Request,
        view: object,
        obj: Any,
    ) -> bool:
        """Allow object access only for the owning shop user.

        Args:
            request (Request): The current request.
            view (object): The view requesting permission.
            obj (Any): The object being checked.

        Returns:
            bool: True when the object is not a shop or is owned by user.
        """
        if isinstance(obj, Shop):
            return obj.user_id == request.user.pk
        return True
