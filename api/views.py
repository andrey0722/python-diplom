import logging
from typing import cast, override

from django.contrib.auth.signals import user_logged_in
from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _
from rest_framework import status
from rest_framework.authentication import authenticate
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .exceptions import EmailConfirmError
from .models import Token
from .models import User
from .serializers import EmailConfirmSerializer
from .serializers import SendEmailVerificationSerializer
from .serializers import TokenSerializer
from .serializers import UserLoginSerializer
from .serializers import UserSerializer
from .services import check_user_token
from .services import send_email_verification_mail
from .services import validate_data

logger = logging.getLogger(__name__)


class UserRegisterView(APIView):
    serializer_class = UserSerializer

    def post(self, request: Request) -> Response:
        """Create a new user and send verification email.

        Args:
            request (Request): The request object.

        Returns:
            Response: The created user data.
        """
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = cast(User, serializer.save())
        send_email_verification_mail(request, user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class SendEmailVerificationView(APIView):
    serializer_class = SendEmailVerificationSerializer

    def post(self, request: Request) -> Response:
        """Send verification email to user.

        Args:
            request (Request): The request object.

        Returns:
            Response: Success message.
        """
        data = validate_data(self.serializer_class, request.data)
        send_email_verification_mail(request, **data)
        return Response(_('Verification email is sent if needed.'))


class EmailConfirmView(APIView):
    serializer_class = EmailConfirmSerializer

    def post(self, request: Request) -> Response:
        """Confirm user email and activate account.

        Args:
            request (Request): The request object.

        Returns:
            Response: Success message.
        """
        data = validate_data(self.serializer_class, request.data)
        user: User | None = data['user']
        token: str = data['token']
        if not check_user_token(user, token):
            raise EmailConfirmError

        # Email confirmed, activate the user
        user = cast(User, user)
        user.is_active = True
        user.save()
        return Response(_('Email successfully verified.'))


class UserLoginView(APIView):
    serializer_class = UserLoginSerializer

    def post(self, request: Request) -> Response:
        credentials = validate_data(self.serializer_class, request.data)

        user = authenticate(cast(HttpRequest, request), **credentials)
        if user is None:
            raise AuthenticationFailed(_('Invalid email or password.'))
        if not user.is_active:
            raise AuthenticationFailed(_('User inactive or deleted.'))

        token = Token.objects.create(user=user)
        # Update last_login
        user_logged_in.send(self, user=user)

        serializer = TokenSerializer(token)
        return Response(serializer.data)


class UserInfoView(RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    permission_classes = (IsAuthenticated,)

    @override
    def get_object(self):  # pyright: ignore[reportIncompatibleMethodOverride]
        # Use only current authorized user
        return self.request.user

    def post(self, request, *args, **kwargs):
        # Also allow POST for updating
        return self.patch(request, *args, **kwargs)
