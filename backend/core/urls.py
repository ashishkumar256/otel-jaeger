from django.urls import path
from .views import sunspot_view, hello, health_check

urlpatterns = [
    path('api/sunspot', sunspot_view),
    path('hello', hello),
    path('status', health_check),
]