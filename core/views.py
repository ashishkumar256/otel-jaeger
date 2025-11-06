import logging
from django.conf import settings
from django.http import HttpResponse
from opentelemetry.trace import get_current_span

logger = logging.getLogger(__name__)

def hello(request):
    span = get_current_span()
    logger.info("Current span: %s", span.get_span_context())
    logger.info(f"Hello view accessed — DEBUG={settings.DEBUG}")    
    return HttpResponse("Hello, world! with span:", span.get_span_context())