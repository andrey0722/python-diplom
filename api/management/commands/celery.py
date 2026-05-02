import logging
from typing import Any

from django.core.management.base import BaseCommand
from django.utils import autoreload

from project import celery_app

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """Management command that runs the Celery worker with autoreload."""

    help = 'Launches celery development server'

    def handle(self, *args: Any, **options: Any) -> None:  # noqa: ARG002
        """Run the Celery worker through Django's autoreloader.

        Args:
            *args (Any): Positional command arguments.
            **options (Any): Parsed command options.
        """
        autoreload.run_with_reloader(self.run_celery)
        logger.info('Celery stopped.')

    def run_celery(self) -> None:
        """Start the development Celery worker."""
        logger.info('Starting celery...')
        celery_app.worker_main(
            [
                'worker',
                '--loglevel',
                'INFO',
                '--pool',
                'solo',
            ]
        )
