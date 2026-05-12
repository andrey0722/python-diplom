from collections.abc import Callable
import functools
import logging
import time
from urllib.parse import urlencode

from django.conf import settings
from django.db import connection
from django.db import reset_queries
from django.http import HttpRequest
from django.http import HttpResponse
from django.shortcuts import redirect
from django.utils.deprecation import MiddlewareMixin
from social_core.exceptions import SocialAuthBaseException
from social_django.middleware import SocialAuthExceptionMiddleware

logger = logging.getLogger(__name__)


def show_debug_toolbar(request: HttpRequest):  # noqa: ARG001
    """Show Django Debug Toolbar in local Docker development."""
    return settings.DEBUG


type RequestHandler = Callable[[HttpRequest], HttpResponse]


class DebugSQLQueryStatsMiddleware(MiddlewareMixin):
    """Middleware that wraps requests with SQL query stats logging."""

    def __init__(self, get_response: RequestHandler) -> None:
        """Initialize middleware object.

        Args:
            get_response (RequestHandler): Next request handler in the chain.
        """
        if settings.SQL_TRACE:
            # Wrap next handler
            get_response = debug_request_sql_stats(get_response)
        super().__init__(get_response)


def debug_request_sql_stats(handler: RequestHandler) -> RequestHandler:
    """Wrap a request handler with SQL query statistics logging.

    Args:
        handler (RequestHandler): Request handler to wrap.

    Returns:
        RequestHandler: Handler that logs SQL query statistics.
    """

    @functools.wraps(handler)
    def wrapper(request: HttpRequest) -> HttpResponse:
        """Log SQL query statistics for a debug request.

        Args:
            request (HttpRequest): The incoming request object.

        Returns:
            HttpResponse: Response returned by the next handler.
        """
        logger.debug('Tracing SQL: %s %s', request.method, request.path)

        reset_queries()
        started_at = time.perf_counter()

        response = handler(request)

        elapsed_ms = (time.perf_counter() - started_at) * 1000
        query_count = len(connection.queries)
        sql_time_ms = sum(float(q['time']) for q in connection.queries) * 1000

        logger.debug(
            'SQL summary: %s %s -> %s queries, %.2f ms SQL, %.2f ms total',
            request.method,
            request.path,
            query_count,
            sql_time_ms,
            elapsed_ms,
        )
        return response

    return wrapper


class SocialAuthAPIExceptionMiddleware(SocialAuthExceptionMiddleware):
    """Redirect social-auth errors to API endpoint with query params."""

    def process_exception(
        self,
        request: HttpRequest,
        exception: Exception,
    ) -> HttpResponse | None:
        """Redirect social-auth exceptions to the configured error URL.

        Args:
            request (HttpRequest): Request that raised the exception.
            exception (Exception): Exception raised by social-auth.

        Returns:
            HttpResponse | None: Redirect response for handled social-auth
                errors, otherwise None.
        """
        strategy = getattr(request, 'social_strategy', None)
        if strategy is None or self.raise_exception(request, exception):
            return None

        if not isinstance(exception, SocialAuthBaseException):
            return None

        backend = getattr(request, 'backend', None)
        backend_name = getattr(backend, 'name', 'unknown-backend')

        message = self.get_message(request, exception)
        url = self.get_redirect_uri(request, exception)

        if not url:
            return None

        query = urlencode({'message': message, 'backend': backend_name})
        separator = '&' if '?' in url else '?'
        url = f'{url}{separator}{query}'
        return redirect(url)
