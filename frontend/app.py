import os
import sys
import logging
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from flask import Flask, render_template

# --- Logging Setup ---
# 1. Configure the standard Python logging formatter to include the OpenTelemetry
#    trace and span IDs, which will be injected by the LoggingInstrumentor.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [trace_id=%(otelTraceID)s span_id=%(otelSpanID)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

# 2. Enable trace context injection for logs. This ensures that logs generated
#    within a request context (which is traced) will have the correlation IDs.
LoggingInstrumentor().instrument(set_logging_format=True, log_level=logging.DEBUG)

# --- Flask Application ---
app = Flask(__name__)

@app.route("/")
def hello():
    # This log line will now include the trace_id and span_id of the current request.
    logging.info("Incoming request received. Rendering index.html.")
    return render_template("index.html")

if __name__ == "__main__":
    # The 'opentelemetry-instrument' wrapper will automatically instrument Flask here.
    app.run(host="0.0.0.0", port=5000)