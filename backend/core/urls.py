from django.urls import path
from . import views

urlpatterns = [
    path('hello', views.hello),
    path('api/sunspot', views.sunspot_view),
    path('api/timeout', views.redis_timeout),
    path('api/factorial', views.factorial),
    path('api/crash', views.div_zero),
    path('status', views.health_check),
    path('exhaust/<str:delay>', views.exhaust),
]