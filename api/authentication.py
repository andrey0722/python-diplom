from rest_framework.authentication import (
    TokenAuthentication as BaseTokenAuthentication,
)

from .models import Token


class TokenAuthentication(BaseTokenAuthentication):
    """Token authentication with custom token model."""

    model = Token
