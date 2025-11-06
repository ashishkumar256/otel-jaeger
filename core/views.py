import logging
from django.conf import settings
from django.http import HttpResponse
from opentelemetry.trace import get_current_span

logger = logging.getLogger(__name__)

def hello(request):
    span = get_current_span()
    span_context = span.get_span_context()
    logger.info("Current span: %s", span_context)
    logger.info(f"Hello view accessed — DEBUG={settings.DEBUG}")    
    return HttpResponse(f"Hello, world! with span: {span_context}")
    try:
        # Try different import paths for auto_instrumentation_loader
        from opentelemetry.instrumentation.auto_instrumentation import (
            _load_instrumentors,
            _import_instrumentor,
        )
        
        # Load all available instrumentors
        instrumentors = _load_instrumentors()
        instrumentations = list(instrumentors.keys())
        
        return JsonResponse({
            'active_instrumentations': instrumentations,
            'count': len(instrumentations)
        })
    except ImportError:
        try:
            # Alternative approach using entry points
            from importlib.metadata import entry_points
            
            instrumentations = []
            eps = entry_points(group='opentelemetry_instrumentor')
            for ep in eps:
                instrumentations.append(ep.name)
                
            return JsonResponse({
                'active_instrumentations': instrumentations,
                'count': len(instrumentations),
                'note': 'This lists available instrumentations, not necessarily active ones'
            })
        except Exception as e:
            return JsonResponse({'error': f"Alternative approach failed: {str(e)}"}, status=500)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)