from django.urls import path
from .views import sunspot_view, health_check

urlpatterns = [
    path('api/sunspot', sunspot_view),
    path('status', health_check),
]