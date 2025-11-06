import logging
import sys
from flask import Flask, render_template
from opentelemetry import trace
from opentelemetry.instrumentation.logging import LoggingInstrumentor

# configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [trace_id=%(otelTraceID)s span_id=%(otelSpanID)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
LoggingInstrumentor().instrument(set_logging_format=True, log_level=logging.DEBUG)

logger = logging.getLogger(__name__)

app = Flask(__name__)

@app.route("/")
def hello():
    # Get the current active span
    current_span = trace.get_current_span()
    span_context = current_span.get_span_context()
    logger.info("Current span context: %s", span_context)
    return render_template("index.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)