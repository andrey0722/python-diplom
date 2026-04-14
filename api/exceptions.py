from django.utils.translation import gettext_lazy as _
from rest_framework import status
from rest_framework.exceptions import APIException


class TokenConfirmError(APIException):
    """Failed to validate user confirmation token."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = _('Invalid email or token.')
    default_code = 'password_reset_error'


class ShopUrlLoadError(APIException):
    """Failed to execute shop pricing URL request."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_detail = _('Could to load shop pricing')
    default_code = 'shop_url_load_error'


class ShopUpdateError(APIException):
    """Unable to apply shop pricing data."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_detail = _('Could not process shop pricing data')
    default_code = 'shop_update_error'
