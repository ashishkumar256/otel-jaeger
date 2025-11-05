import logging
from django.http import HttpResponse
from opentelemetry.trace import get_current_span

logger = logging.getLogger(__name__)

def hello(request):
    span = get_current_span()
    print("Current span:", span.get_span_context())
    return HttpResponse("Hello, world! with span:", span.get_span_context())