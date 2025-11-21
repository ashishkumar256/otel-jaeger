import os
import sys
import logging
import requests
from flask import Flask, request
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

# Get a tracer for manual instrumentation
tracer = trace.get_tracer(__name__)

app = Flask(__name__)

# configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [trace_id=%(otelTraceID)s span_id=%(otelSpanID)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
LoggingInstrumentor().instrument(set_logging_format=True, log_level=logging.DEBUG)

logger = logging.getLogger(__name__)
sunspot_service = os.environ.get('SUNSPOT_BACKEND_ENDPOINT', "http://localhost:8000")

# Business logic with manual tracing
def fetch_sunspot(endpoint):
    # Start a manual span for the external API call
    with tracer.start_as_current_span("sunspot.backend_api_call") as span:
        try:
            # Add business context to the span
            span.set_attribute("http.url", endpoint)
            span.set_attribute("business.service", "sunspot_lookup")

            logger.info(f"Fetching sunspot data from: {endpoint}")

            # Get API key from environment variable
            api_key = os.environ.get('SUNSPOT_API_KEY')
            if not api_key:
                logger.error("SUNSPOT_API_KEY environment variable not set")
                span.set_status(Status(StatusCode.ERROR, "API key not configured"))
                span.set_attribute("error.type", "configuration_error")
                return "Internal server error: API key not configured", 500

            headers = {
                'X-API-KEY': api_key
            }

            logger.debug(f"Making request with API key: {api_key[:8]}...")  # Log partial key for security

            # Record the start time for latency measurement
            span.add_event("starting_backend_api_request")

            response = requests.get(endpoint, headers=headers)
            response.raise_for_status()

            # Record success metrics
            span.set_attribute("http.status_code", response.status_code)
            span.add_event("backend_api_request_successful")
            logger.info(f"Successfully fetched sunspot data, status: {response.status_code}")
            return response.text, response.status_code
        except requests.exceptions.HTTPError as e:
            # Record detailed error information
            span.set_status(Status(StatusCode.ERROR, f"HTTP error: {e}"))
            span.set_attribute("http.status_code", e.response.status_code)
            span.set_attribute("error.type", "http_error")

            if e.response.status_code == 401:
                logger.error(f"Authentication failed - invalid API key for {endpoint}")
                span.set_attribute("auth.error", "invalid_api_key")
                return "Authentication failed: Invalid API key", 401
            elif e.response.status_code == 504:
                logger.error(f"Backend reported a Gateway Timeout (504) for {endpoint}")
                span.set_attribute("timeout.error", "backend_timeout")
                return f"Backend timeout error: {e.response.text}", 504
            else:
                logger.error(f"HTTP error fetching sunspot data from {endpoint}: {str(e)}")
                return f"Error fetching sun spot timings: {e.response.text}", e.response.status_code
        except requests.exceptions.RequestException as e:
            span.set_status(Status(StatusCode.ERROR, f"Request error: {e}"))
            span.set_attribute("error.type", "network_error")
            span.set_attribute("error.details", str(e))
            logger.error(f"Error fetching sunspot data from {endpoint}: {str(e)}")
            return f"Error fetching sun spot timings: {e}", 503

@app.route('/sunspot')
def sunspot_combined_query():
    """
    Route to get sunspot data using either 'city' or 'lat'/'lon' query parameters,
    now including an optional 'date' parameter.
    """
    # Start a manual span for the entire business operation
    with tracer.start_as_current_span("sunspot.lookup") as span:
        city = request.args.get('city')
        lat = request.args.get('lat')
        lon = request.args.get('lon')
        date = request.args.get('date')

        # Add ALL business context to the span
        span.set_attribute("business.operation", "sunspot_lookup")
        span.set_attribute("user.input.city", city or "not_provided")
        span.set_attribute("user.input.lat", lat or "not_provided")
        span.set_attribute("user.input.lon", lon or "not_provided")
        span.set_attribute("user.input.date", date or "not_provided")
        span.set_attribute("lookup.type", "city" if city else "coordinates")

        logger.info(f"Received request - city: {city}, lat: {lat}, lon: {lon}, date: {date}")

        # Start endpoint construction
        endpoint = f'{sunspot_service}/api/sunspot?'
        query_parts = []

        if city:
            # Querying by city
            query_parts.append(f'city={city}')
            span.set_attribute("business.city_name", city)
        elif lat and lon:
            # Querying by coordinates
            query_parts.append(f'lat={lat}')
            query_parts.append(f'lon={lon}')
            span.set_attribute("business.coordinates", f"{lat},{lon}")
        else:
            # Missing required parameters
            span.set_status(Status(StatusCode.ERROR, "Missing required parameters"))
            span.set_attribute("error.type", "validation_error")
            logger.warning("Missing required query parameters: either 'city' or 'lat'/'lon'")
            return "Missing 'city' or 'lat'/'lon' query parameters.\n", 400

        # Add optional date parameter if provided
        if date:
            query_parts.append(f'date={date}')
            span.set_attribute("business.requested_date", date)

        # Combine all query parts to form the final endpoint
        endpoint += '&'.join(query_parts)

        span.set_attribute("backend.endpoint", endpoint)
        logger.debug(f"Constructed backend endpoint: {endpoint}")

        # Record that we're about to make the backend call
        span.add_event("initiating_backend_call")

        result, status = fetch_sunspot(endpoint)

        # Record the outcome
        span.set_attribute("http.response.status", status)
        if status == 200:
            span.add_event("sunspot_lookup_successful")
        else:
            span.set_status(Status(StatusCode.ERROR, f"Backend returned error: {status}"))

        logger.info(f"Request completed with status: {status}")
        return result, status

@app.route('/test/timeout')
def sunspot_timeout_test():
    """Route to test backend Redis timeout error."""
    with tracer.start_as_current_span("sunspot.timeout_test") as span:
        span.set_attribute("test.type", "redis_timeout")
        endpoint = f'{sunspot_service}/api/timeout'
        logger.info(f"Calling backend timeout test endpoint: {endpoint}")
        
        result, status = fetch_sunspot(endpoint)
        span.set_attribute("test.result_status", status)
        return result, status

@app.route('/test/crash')
def sunspot_crash_test():
    """Route to test backend unhandled exception/crash."""
    with tracer.start_as_current_span("sunspot.crash_test") as span:
        span.set_attribute("test.type", "zero_division")
        endpoint = f'{sunspot_service}/api/crash'
        logger.info(f"Calling backend crash test endpoint: {endpoint}")
        
        result, status = fetch_sunspot(endpoint)
        span.set_attribute("test.result_status", status)
        return result, status

@app.route('/exhaust/<float:delay>')
def exhaust_data(delay):
    """Frontend route for delay simulation"""
    with tracer.start_as_current_span("data.exhaust") as span:
        span.set_attribute("exhaust.requested", delay)

        endpoint = f'{sunspot_service}/api/exhaust/{delay}'

        result, status = fetch_sunspot(endpoint)
        return result, status

@app.route('/factorial/<int:n>', methods=['GET'])
def factorial_route(n):
    with tracer.start_as_current_span("frontend.factorial_request") as span:
        span.set_attribute("factorial.input", n)
        logger.info(f"Frontend request for factorial of {n}")
        resp = requests.get(f"{sunspot_service}/api/factorial/{n}")
        data = resp.json()
        span.set_attribute("http.status_code", resp.status_code)
        if resp.status_code != 200:
            span.set_attribute("error.type", data.get("error", "unknown"))
        return data, resp.status_code

@app.route('/health')
def health_check():
    return 'OK', 200

if __name__ == '__main__':
    logger.info("Starting Sunspot Flask application")
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))