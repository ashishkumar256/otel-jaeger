import logging
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from opentelemetry.trace import get_current_span
from opentelemetry.instrumentation import auto_instrumentation_loader

logger = logging.getLogger(__name__)

def hello(request):
    span = get_current_span()
    logger.info("Current span: %s", span.get_span_context())
    logger.info(f"Hello view accessed — DEBUG={settings.DEBUG}")    
    return HttpResponse("Hello, world! with span:", span.get_span_context())

def list_instrumentations(request):
    try:
        instrumentors = auto_instrumentation_loader._get_instrumentors()
        instrumentations = list(instrumentors.keys())
        return JsonResponse({
            'active_instrumentations': instrumentations,
            'count': len(instrumentations)
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)