import re
from typing import TYPE_CHECKING, Any, cast, override

from rest_framework import throttling
from rest_framework.request import Request

if TYPE_CHECKING:
    from rest_framework.views import APIView


class ExtendedRateThrottle(throttling.SimpleRateThrottle):
    """Throttle base class that supports multiplied rate periods."""

    period_re = re.compile(r'^(?P<multiplier>\d+)?(?P<unit>[a-zA-Z]+)$')
    units_duration = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}

    @override
    def parse_rate(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        rate: str | None,
    ) -> tuple[int | None, int | None]:
        """Parse request count and duration from a throttle rate string.

        Supports DRF rates with a numeric multiplier before the period unit,
        such as `1/3min` or `1/5sec`.

        Args:
            rate (str | None): Throttle rate in `count/period` format.

        Returns:
            tuple[int | None, int | None]: Request count and duration in
                seconds, or two None values when rate is None.

        Raises:
            ValueError: If the period cannot be parsed.
        """
        if rate is None:
            return None, None

        num, period = rate.split('/')
        num_requests = int(num)

        match = self.period_re.fullmatch(period.strip())
        if match is None:
            raise ValueError(f'Invalid throttle period {period!r}.')

        num_unit, unit = match.group('multiplier', 'unit')
        multiplier = int(num_unit or 1)
        duration = self.units_duration[unit[0]] * multiplier

        return num_requests, duration


class AnonRateThrottle(  # pyright: ignore[reportIncompatibleMethodOverride]
    ExtendedRateThrottle,
    throttling.AnonRateThrottle,
):
    """Limits the rate of API calls made by an anonymous user."""


class UserRateThrottle(  # pyright: ignore[reportIncompatibleMethodOverride]
    ExtendedRateThrottle,
    throttling.UserRateThrottle,
):
    """Limits the rate of API calls made by an authenticated user."""

    @override
    def get_cache_key(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        request: Request,
        view: 'APIView',
    ) -> str | None:
        """Build a cache key only for authenticated users.

        Args:
            request (Request): The current request.
            view (APIView): The view being throttled.

        Returns:
            str | None: Cache key for authenticated users, otherwise None.
        """
        if not request.user or not request.user.is_authenticated:
            return None  # Only throttle authenticated requests

        ident = request.user.pk
        return self.cache_format % {'scope': self.scope, 'ident': ident}


class ScopedRateThrottle(  # pyright: ignore[reportIncompatibleMethodOverride]
    ExtendedRateThrottle,
    throttling.ScopedRateThrottle,
):
    """Scoped throttle with extended period parsing."""


class EmailScopedRateThrottle(ScopedRateThrottle):
    """Scoped throttle keyed by normalized email request data."""

    cache_format = 'email_%(scope)s_%(ident)s'
    scope_attr = 'throttle_email_scope'

    @override
    def get_cache_key(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        request: Request,
        view: 'APIView',
    ) -> str | None:
        """Build a cache key from the submitted email address.

        Args:
            request (Request): The current request.
            view (APIView): The view being throttled.

        Returns:
            str | None: Cache key for valid email input, otherwise None.
        """
        data = cast(dict[str, Any], request.data)
        email = data.get('email')

        if not isinstance(email, str) or not (email := email.strip()):
            return None

        return self.cache_format % {
            'scope': self.scope,
            'ident': email.casefold(),
        }
