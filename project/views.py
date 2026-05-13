from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import logout
from django.http import HttpRequest
from django.http import HttpResponse
from django.shortcuts import redirect

from .exceptions import SampleError


@staff_member_required
def trigger_error(request: HttpRequest) -> HttpResponse:  # noqa: ARG001
    """Raise a sample error for staff-only error reporting checks.

    Args:
        request (HttpRequest): Incoming staff-only request.

    Raises:
        SampleError: Always raised to exercise error reporting.
    """
    raise SampleError
    return HttpResponse('Sample error')


def health_check(request: HttpRequest) -> HttpResponse:  # noqa: ARG001
    """Return a simple response for service health probes.

    Args:
        request (HttpRequest): Incoming health check request.

    Returns:
        HttpResponse: Response indicating the service is available.
    """
    return HttpResponse('OK')


def social_login(request: HttpRequest, backend: str) -> HttpResponse:
    """Start social login after clearing any existing session.

    Args:
        request (HttpRequest): Incoming social login request.
        backend (str): Social authentication backend name.

    Returns:
        HttpResponse: Redirect response to the social-auth backend.
    """
    # We might have a session from Django admin, don't use it
    logout(request)
    return redirect('social:begin', backend=backend)
