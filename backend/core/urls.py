from django.urls import path
from .views import sunspot_view, hello, health_check, redis_timeout, div_zero

urlpatterns = [
    path('api/sunspot', sunspot_view),
    path('api/timeout', redis_timeout),
    path('api/crash', div_zero),
    path('hello', hello),
    path('status', health_check),
]