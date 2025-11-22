from django.urls import path #re_path
from . import views

urlpatterns = [
    path('status', views.health_check),
    path('api/hello/<str:name>', views.hello),
    path('api/sunspot', views.sunspot_view),
    path('api/factorial/<str:n>', views.factorial),
    path('api/delay/<str:delay>', views.latency),
    path('api/timeout', views.redis_timeout),
    path('api/crash', views.div_zero),
    # re_path(r'^api/factorial/(?P<n>-?\d+)/?$', views.factorial),
]