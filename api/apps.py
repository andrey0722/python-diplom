from typing import override

from django.apps import AppConfig


class ApiConfig(AppConfig):
    """Django app configuration class."""

    name = 'api'

    @override
    def ready(self):
        """Run application startup logic when Django app is initialized."""
        from . import utils  # noqa: F401, PLC0415
