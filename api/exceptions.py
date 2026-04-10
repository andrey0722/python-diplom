from django.utils.translation import gettext_lazy as _
from rest_framework import status
from rest_framework.exceptions import APIException


class EmailConfirmError(APIException):
    """Failed to confirm user email."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = _('Invalid email or token.')
    default_code = 'email_confirm_error'
