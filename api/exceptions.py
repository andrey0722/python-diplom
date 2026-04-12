from django.utils.translation import gettext_lazy as _
from rest_framework import status
from rest_framework.exceptions import APIException


class TokenConfirmError(APIException):
    """Failed to validate user confirmation token."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = _('Invalid email or token.')
    default_code = 'password_reset_error'
