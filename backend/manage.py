#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys
import logging

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider, export
from opentelemetry.instrumentation.django import DjangoInstrumentor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.logging import LoggingInstrumentor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [trace_id=%(otelTraceID)s span_id=%(otelSpanID)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

LoggingInstrumentor().instrument(set_logging_format=True, log_level=logging.DEBUG)


logger = logging.getLogger("sunspot")

def main():
    """Run administrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')

    # Otel client config
    try:
        trace.set_tracer_provider(TracerProvider())
        trace.get_tracer_provider().add_span_processor(
            export.BatchSpanProcessor(OTLPSpanExporter())
        )

        DjangoInstrumentor().instrument()
        logger.warning(f"OpenTelemetry instrumentation successful")
    except Exception as e:
        logger.warning(f"OpenTelemetry instrumentation failed: {e}")


    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
