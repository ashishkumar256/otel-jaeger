from django.urls import path
from .views import hello, list_instrumentations

urlpatterns = [
    path('api/hello', hello),
]