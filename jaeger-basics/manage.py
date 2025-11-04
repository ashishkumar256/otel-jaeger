#!/usr/bin/env python
import os
import sys
from otel_config import configure_opentelemetry

if __name__ == "__main__":
    configure_opentelemetry()
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "jaeger_basics.settings")
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)
