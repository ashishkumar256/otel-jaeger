import os
import sys
import logging
import requests
from flask import Flask, request
from opentelemetry.instrumentation.logging import LoggingInstrumentor

app = Flask(__name__)

# Initialize environment variables once
sunspot_service = os.environ.get('SUNSPOT_BACKEND_ENDPOINT', "http://localhost:8000")
API_KEY = os.environ.get('SUNSPOT_API_KEY')

# configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [trace_id=%(otelTraceID)s span_id=%(otelSpanID)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
LoggingInstrumentor().instrument(set_logging_format=True, log_level=logging.DEBUG)

logger = logging.getLogger(__name__)

# Business logic
def fetch_sunspot(endpoint):
    try:
        logger.info(f"Fetching data from: {endpoint}")

        # Use the globally initialized API_KEY
        if not API_KEY:
            logger.error("SUNSPOT_API_KEY environment variable not set")
            return "Internal server error: API key not configured", 500

        headers = {
            'X-API-KEY': API_KEY
        }

        logger.debug(f"Making request with API key: {API_KEY[:8]}...")

        response = requests.get(endpoint, headers=headers)
        response.raise_for_status()
        logger.info(f"Successfully fetched data, status: {response.status_code}")
        return response.text, response.status_code
    except requests.exceptions.HTTPError as e:
        # Capture the backend's status code and response body for better tracing
        status_code = e.response.status_code
        error_text = e.response.text if e.response is not None else str(e)
        
        if status_code == 401:
            logger.error(f"Authentication failed - invalid API key for {endpoint}")
            return "Authentication failed: Invalid API key", 401
        elif status_code == 504:
            logger.error(f"Backend reported a Gateway Timeout (504) for {endpoint}")
            return error_text, 504
        elif status_code >= 500:
            logger.error(f"Backend returned Internal Server Error ({status_code}) from {endpoint}: {error_text}")
            return f"Backend Service Error: {error_text}", status_code
        else:
            logger.error(f"HTTP error fetching data from {endpoint}: {str(e)}")
            return f"Error fetching data: {error_text}", status_code
    except requests.exceptions.RequestException as e:
        logger.error(f"Network/Connection error fetching data from {endpoint}: {str(e)}")
        # Use 503 Service Unavailable for connection issues
        return f"Backend connection error: {e}", 503

@app.route('/sunspot')
def sunspot_combined_query():
    """
    Route to get sunspot data using either 'city' or 'lat'/'lon' query parameters,
    now including an optional 'date' parameter.
    """
    city = request.args.get('city')
    lat = request.args.get('lat')
    lon = request.args.get('lon')
    date = request.args.get('date')

    logger.info(f"Received request - city: {city}, lat: {lat}, lon: {lon}, date: {date}")

    # Use the globally initialized sunspot_service
    # Start endpoint construction
    endpoint = f'{sunspot_service}/api/sunspot?'
    query_parts = []

    if city:
        query_parts.append(f'city={city}')
    elif lat and lon:
        query_parts.append(f'lat={lat}')
        query_parts.append(f'lon={lon}')
    else:
        logger.warning("Missing required query parameters: either 'city' or 'lat'/'lon'")
        return "Missing 'city' or 'lat'/'lon' query parameters.\n", 400

    if date:
        query_parts.append(f'date={date}')

    # Combine all query parts to form the final endpoint
    endpoint += '&'.join(query_parts)

    logger.debug(f"Constructed backend endpoint: {endpoint}")
    result, status = fetch_sunspot(endpoint)
    logger.info(f"Request completed with status: {status}")
    return result, status

@app.route('/test/timeout')
def sunspot_timeout_test():
    """Route to test backend Redis timeout error."""
    # Use the globally initialized sunspot_service
    endpoint = f'{sunspot_service}/api/timeout'
    logger.info(f"Calling backend timeout test endpoint: {endpoint}")
    result, status = fetch_sunspot(endpoint)
    return result, status

@app.route('/test/crash')
def sunspot_crash_test():
    """Route to test backend unhandled exception/crash."""
    # Use the globally initialized sunspot_service
    endpoint = f'{sunspot_service}/api/crash'
    logger.info(f"Calling backend crash test endpoint: {endpoint}")
    result, status = fetch_sunspot(endpoint)
    return result, status

@app.route('/health')
def health_check():
    return 'OK', 200

if __name__ == '__main__':
    logger.info("Starting Sunspot Flask application")
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))