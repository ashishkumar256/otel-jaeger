from django.urls import path
from .views import sunspot_view

urlpatterns = [
    path('api/sunspot', sunspot_view),
]