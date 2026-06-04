from .request_logging import log_api_request


class APIRequestLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if request.path.startswith("/api/"):
            log_api_request(request, response)

        return response
