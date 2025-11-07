import os
import sys
import logging
import requests
from flask import Flask, request
from opentelemetry.instrumentation.logging import LoggingInstrumentor

app = Flask(__name__)

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
        logger.info(f"Fetching sunspot data from: {endpoint}")
        response = requests.get(endpoint)
        response.raise_for_status()
        logger.info(f"Successfully fetched sunspot data, status: {response.status_code}")
        return response.text, response.status_code
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching sunspot data from {endpoint}: {str(e)}")
        return f"Error fetching sun spot timings: {e}", 503

@app.route('/sunspot')
def sunspot_combined_query():
    """
    Route to get sunspot data using either 'city' or 'lat'/'lon' query parameters,
    now including an optional 'date' parameter.
    """

    city = request.args.get('city')
    lat = request.args.get('lat')
    lon = request.args.get('lon')
    date = request.args.get('date') # Extract the new date parameter

    logger.info(f"Received request - city: {city}, lat: {lat}, lon: {lon}, date: {date}")

    sunspot_service = os.environ.get('SUNSPOT_BACKEND_ENDPOINT', "http://localhost:8000")
    # Start endpoint construction
    endpoint = f'{sunspot_service}/api/sunspot?'
    query_parts = []

    if city:
        # Querying by city
        query_parts.append(f'city={city}')
    elif lat and lon:
        # Querying by coordinates
        query_parts.append(f'lat={lat}')
        query_parts.append(f'lon={lon}')
    else:
        # Missing required parameters
        logger.warning("Missing required query parameters: either 'city' or 'lat'/'lon'")
        return "Missing 'city' or 'lat'/'lon' query parameters.\n", 400

    # Add optional date parameter if provided
    if date:
        query_parts.append(f'date={date}')

    # Combine all query parts to form the final endpoint
    endpoint += '&'.join(query_parts)

    logger.debug(f"Constructed backend endpoint: {endpoint}")
    result, status = fetch_sunspot(endpoint)
    logger.info(f"Request completed with status: {status}")
    return result, status

@app.route('/health')
def health_check():
    return 'OK', 200

if __name__ == '__main__':
    logger.info("Starting Sunspot Flask application")
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))