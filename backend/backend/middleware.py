from django.http import JsonResponse
from core.models import ApiKey

class APIKeyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/api/"):
            api_key = request.headers.get("X-API-KEY")
            if not api_key:
                return JsonResponse({"detail": "Missing API key"}, status=401)

            if not ApiKey.objects.filter(key=api_key).exists():
                return JsonResponse({"detail": "Invalid API key"}, status=403)

        return self.get_response(request)