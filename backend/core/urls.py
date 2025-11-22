from django.urls import path
from . import views

urlpatterns = [
    path('hello', views.hello),
    path('status', views.health_check),
    path('api/sunspot', views.sunspot_view),
    path('api/timeout', views.redis_timeout),
    path('api/factorial/<int:n>', views.factorial),
    path('api/exhaust/<str:delay>', views.exhaust),
]