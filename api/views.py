from typing import Any, cast

from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _
from rest_framework.authentication import authenticate
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.generics import CreateAPIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Token
from .models import User
from .serializers import TokenSerializer
from .serializers import UserLoginSerializer
from .serializers import UserSerializer


class UserRegisterView(CreateAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer


class UserLoginView(APIView):
    serializer_class = UserLoginSerializer

    def post(self, request: Request) -> Response:
        serializer = UserLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        credentials = cast(dict[str, Any], serializer.data)

        user = authenticate(cast(HttpRequest, request), **credentials)
        if user is None:
            raise AuthenticationFailed(_('Invalid username or password.'))
        if not user.is_active:
            raise AuthenticationFailed(_('User inactive or deleted.'))

        token = Token.objects.create(user=user)
        serializer = TokenSerializer(token)
        return Response(serializer.data)
