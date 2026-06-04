from .request_logging import log_api_request


class APIRequestLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Ignore dashboard UI endpoints so they don't spam the activity feed
        ignored_endpoints = {
            "/api/dashboard/",
            "/api/dashboard-data/",
            "/api/api-activity/",
            "/api/system-summary/",
            "/api/servers/",
            "/api/metrics/",
        }

        if request.path.startswith("/api/") and request.path not in ignored_endpoints:
            log_api_request(request, response)

        return response
