from django.http import HttpRequest
from django.http import HttpResponse


def health_check(request: HttpRequest) -> HttpResponse:  # noqa: ARG001
    """Return a simple response for service health probes.

    Args:
        request (HttpRequest): Incoming health check request.

    Returns:
        HttpResponse: Response indicating the service is available.
    """
    return HttpResponse('OK')
