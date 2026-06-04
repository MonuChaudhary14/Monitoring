import ipaddress

from .models import APIRequestLog, Server


def get_request_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        candidate = forwarded_for.split(",")[0].strip()
    else:
        candidate = request.META.get("REMOTE_ADDR")

    if not candidate:
        return None

    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def detect_request_source(request):
    if request.headers.get("X-API-KEY"):
        return "agent"

    referer = request.headers.get("Referer", "")
    if "/api/dashboard/" in referer:
        return "dashboard"

    return "external"


def resolve_server_for_request(request):
    if hasattr(request, "monitoring_server"):
        return request.monitoring_server

    api_key = request.headers.get("X-API-KEY")
    if not api_key:
        return None

    return Server.objects.filter(api_key=api_key).first()


def log_api_request(request, response):
    server = resolve_server_for_request(request)
    APIRequestLog.objects.create(
        server=server,
        endpoint=request.path,
        method=request.method,
        status_code=response.status_code,
        source=detect_request_source(request),
        ip_address=get_request_ip(request),
    )
