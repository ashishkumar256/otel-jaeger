import json 
import time 
import logging 
from datetime import date, timedelta 
import redis 
import requests 
from dateutil import parser 
from django.conf import settings 
from django.http import HttpResponse, JsonResponse
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

# Get tracer for manual instrumentation
tracer = trace.get_tracer(__name__)

logger = logging.getLogger("sunspot")

def hello(request):
    span = trace.get_current_span()
    span_context = span.get_span_context()
    logger.info("Current span: %s", span_context)
    logger.info(f"Hello view accessed — DEBUG={settings.DEBUG}")    
    return HttpResponse(f"Hello, world! with span: {span_context}")

def initialize_redis_client(conn_retry_count=1):
    try:
        r = redis.Redis(
            host=settings.REDIS_HOST,
            port=int(settings.REDIS_PORT),
            decode_responses=True,
            socket_connect_timeout=10,
            socket_timeout=5,
        )
        r.ping()
        logger.info(f"Connected to Redis at {settings.REDIS_SERVER}")
        return r
    except Exception as e:
        logger.warning(f"Attempt {conn_retry_count}: Could not connect to Redis at {settings.REDIS_SERVER}: {e}")
        if conn_retry_count < getattr(settings, "REDIS_CONN_RETRY_COUNT", 3):
            time.sleep(1)
            return initialize_redis_client(conn_retry_count + 1)
        logger.error("Failed to connect to Redis after maximum retries.")
        return None

redis_client = initialize_redis_client()

def resolve_date_param(date_param):
    """Resolve date parameter to YYYY-MM-DD format"""
    with tracer.start_as_current_span("resolve_date_parameter") as span:
        span.set_attribute("date.input", date_param or "not_provided")
        
        today = date.today()
        if not date_param or date_param.lower() == 'today':
            result = today.strftime('%Y-%m-%d')
        elif date_param.lower() == 'yesterday':
            result = (today - timedelta(days=1)).strftime('%Y-%m-%d')
        elif date_param.lower() == 'tomorrow':
            result = (today + timedelta(days=1)).strftime('%Y-%m-%d')
        else:
            try:
                result = parser.parse(date_param).strftime('%Y-%m-%d')
            except ValueError:
                span.set_status(Status(StatusCode.ERROR, "Invalid date format"))
                span.set_attribute("error.type", "date_parsing_error")
                result = None
        
        span.set_attribute("date.resolved", result or "invalid")
        return result

def get_coordinates_from_city(city):
    """Get latitude and longitude from city name using Nominatim"""
    with tracer.start_as_current_span("geocode.city_to_coordinates") as span:
        span.set_attribute("geocode.city", city)
        span.set_attribute("external.service", "nominatim")
        
        try:
            response = requests.get(
                settings.NOMINATIM_SEARCH_URL,
                params={"q": city, "format": "json", "limit": 1},
                headers={"User-Agent": "SunspotMinimal/1.0"}
            )
            response.raise_for_status()
            data = response.json()
            
            if data and data[0].get("lat") and data[0].get("lon"):
                lat, lon = data[0]["lat"], data[0]["lon"]
                span.set_attribute("geocode.found", True)
                span.set_attribute("geocode.latitude", lat)
                span.set_attribute("geocode.longitude", lon)
                span.add_event("geocode_successful")
                return lat, lon
            else:
                span.set_attribute("geocode.found", False)
                span.set_status(Status(StatusCode.ERROR, "City not found"))
                return None, None
                
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, f"Geocoding failed: {e}"))
            span.set_attribute("error.type", "geocoding_error")
            logger.warning(f"Error fetching coordinates for city '{city}': {e}")
            return None, None

def get_city_from_coordinates(lat, lon):
    """Get city name from coordinates using Nominatim reverse geocoding"""
    with tracer.start_as_current_span("geocode.coordinates_to_city") as span:
        span.set_attribute("geocode.latitude", lat)
        span.set_attribute("geocode.longitude", lon)
        span.set_attribute("external.service", "nominatim")
        
        try:
            response = requests.get(
                settings.NOMINATIM_REVERSE_URL,
                params={"lat": lat, "lon": lon, "format": "json"},
                headers={"User-Agent": "SunspotMinimal/1.0"}
            )
            response.raise_for_status()
            data = response.json()
            address = data.get("address", {})
            city_name = (
                address.get("city") or 
                address.get("town") or 
                address.get("village") or 
                address.get("hamlet") or 
                "Unknown"
            )
            
            span.set_attribute("geocode.city_found", city_name)
            span.add_event("reverse_geocode_successful")
            return city_name
            
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, f"Reverse geocoding failed: {e}"))
            span.set_attribute("error.type", "reverse_geocoding_error")
            logger.warning(f"Error reverse geocoding {lat}, {lon}: {e}")
            return "Unknown"

def get_cached_sunspot_by_city(city_name, date_str):
    """Get any cached sunspot data for a city (any coordinates within that city)"""
    with tracer.start_as_current_span("cache.lookup_by_city") as span:
        span.set_attribute("cache.strategy", "city_based")
        span.set_attribute("cache.city", city_name)
        span.set_attribute("cache.date", date_str)
        
        if not redis_client:
            span.set_attribute("cache.available", False)
            return None, None, None
        
        # Search for any cached data for this city and date
        pattern = f"{settings.REDIS_KEY_PREFIX}:{city_name.lower()}:*:{date_str}"
        span.set_attribute("cache.pattern", pattern)
        keys = redis_client.keys(pattern)
        
        if keys:
            # Return the first matching cached data
            cached_data = redis_client.get(keys[0])
            if cached_data:
                try:
                    # Extract coordinates from the key
                    # Format: sunspot:data:city:lat:lon:date
                    key_parts = keys[0].split(":")
                    cached_city = key_parts[2]  # city name
                    cached_lat = key_parts[3]   # latitude
                    cached_lon = key_parts[4]   # longitude
                    sun_data = json.loads(cached_data)
                    
                    span.set_attribute("cache.hit", True)
                    span.set_attribute("cache.found_coordinates", f"{cached_lat},{cached_lon}")
                    span.add_event("cache_hit_city_based")
                    return sun_data, cached_lat, cached_lon
                except (json.JSONDecodeError, IndexError) as e:
                    span.set_status(Status(StatusCode.ERROR, f"Cache data corrupted: {e}"))
                    span.set_attribute("error.type", "cache_corruption")
                    logger.warning(f"Error decoding cached sunspot data: {e}")
        
        span.set_attribute("cache.hit", False)
        span.add_event("cache_miss_city_based")
        return None, None, None

def get_cached_sunspot_by_coords(lat, lon, date_str):
    """Get cached sunspot data by exact coordinates"""
    with tracer.start_as_current_span("cache.lookup_by_coordinates") as span:
        span.set_attribute("cache.strategy", "coordinate_based")
        span.set_attribute("cache.latitude", lat)
        span.set_attribute("cache.longitude", lon)
        span.set_attribute("cache.date", date_str)
        
        if not redis_client:
            span.set_attribute("cache.available", False)
            return None, None
        
        # Search for cached data with these exact coordinates
        pattern = f"{settings.REDIS_KEY_PREFIX}:*:{lat}:{lon}:{date_str}"
        span.set_attribute("cache.pattern", pattern)
        keys = redis_client.keys(pattern)
        
        if keys:
            cached_data = redis_client.get(keys[0])
            if cached_data:
                try:
                    # Extract city name from cache key
                    # Format: sunspot:data:city:lat:lon:date
                    key_parts = keys[0].split(":")
                    cached_city = key_parts[2]  # city name
                    sun_data = json.loads(cached_data)
                    
                    span.set_attribute("cache.hit", True)
                    span.set_attribute("cache.found_city", cached_city)
                    span.add_event("cache_hit_coordinate_based")
                    return sun_data, cached_city
                except (json.JSONDecodeError, IndexError) as e:
                    span.set_status(Status(StatusCode.ERROR, f"Cache data corrupted: {e}"))
                    span.set_attribute("error.type", "cache_corruption")
                    logger.warning(f"Error decoding cached data: {e}")
        
        span.set_attribute("cache.hit", False)
        span.add_event("cache_miss_coordinate_based")
        return None, None

def get_sunspot(lat, lon, date_param, city_name=None):
    """Get sunspot data from API or cache"""
    with tracer.start_as_current_span("sunspot.data_retrieval") as span:
        span.set_attribute("sunspot.latitude", lat)
        span.set_attribute("sunspot.longitude", lon)
        span.set_attribute("sunspot.date_param", date_param or "not_provided")
        if city_name:
            span.set_attribute("sunspot.city_name", city_name)
        
        resolved_date_str = resolve_date_param(date_param)
        if not resolved_date_str:
            span.set_status(Status(StatusCode.ERROR, "Invalid date parameter"))
            return None, None, None
        
        span.set_attribute("sunspot.resolved_date", resolved_date_str)
        ttl = settings.CACHE_TTL
        sun_data = None
        source = "api"  # Track where we got the data from
        
        # If city_name is not provided, get it from coordinates
        if not city_name:
            city_name = get_city_from_coordinates(lat, lon)
            span.set_attribute("sunspot.resolved_city", city_name)
        
        # Create cache key
        cache_key = f"{settings.REDIS_KEY_PREFIX}:{city_name.lower()}:{lat}:{lon}:{resolved_date_str}"
        span.set_attribute("cache.key", cache_key)
        
        # Try to get from cache first
        if redis_client:
            with tracer.start_as_current_span("cache.lookup") as cache_span:
                cached_data = redis_client.get(cache_key)
                if cached_data:
                    logger.info(f"Cache HIT for key: {cache_key}")
                    cache_span.set_attribute("cache.hit", True)
                    cache_span.add_event("cache_hit")
                    try:
                        sun_data = json.loads(cached_data)
                        source = "cache"
                        return sun_data, resolved_date_str, city_name
                    except json.JSONDecodeError:
                        cache_span.set_status(Status(StatusCode.ERROR, "Cache data corrupted"))
                        cache_span.set_attribute("error.type", "cache_corruption")
                        logger.warning("Error decoding cached data, fetching from API.")
                        sun_data = None
                else:
                    cache_span.set_attribute("cache.hit", False)
                    cache_span.add_event("cache_miss")
        
        # Fetch from API if not in cache
        if sun_data is None:
            with tracer.start_as_current_span("external.api_call") as api_span:
                logger.info(f"Cache MISS, fetching from API for key: {cache_key}")
                api_span.set_attribute("external.api.url", settings.SUNRISE_SUNSET_API_URL)
                api_span.set_attribute("external.api.params", f"lat={lat},lng={lon},date={resolved_date_str}")
                
                try:
                    params = {"lat": lat, "lng": lon, "date": resolved_date_str}
                    response = requests.get(settings.SUNRISE_SUNSET_API_URL, params=params)
                    response.raise_for_status()
                    data = response.json()
                    
                    api_span.set_attribute("external.api.status_code", response.status_code)
                    
                    if data.get("status") == "OK":
                        sun_data = data["results"]
                        api_span.add_event("external_api_success")
                        
                        # Cache the result
                        if sun_data and redis_client:
                            with tracer.start_as_current_span("cache.store") as store_span:
                                redis_client.set(cache_key, json.dumps(sun_data), ex=ttl)
                                store_span.set_attribute("cache.ttl_seconds", ttl)
                                store_span.add_event("cache_stored")
                                logger.info(f"Cache SET for key: {cache_key} with TTL: {ttl}s")
                    else:
                        api_span.set_status(Status(StatusCode.ERROR, "API returned error status"))
                        api_span.set_attribute("external.api.error_status", data.get("status"))
                        
                except Exception as e:
                    api_span.set_status(Status(StatusCode.ERROR, f"API call failed: {e}"))
                    api_span.set_attribute("error.type", "external_api_error")
                    logger.error(f"Error fetching sunspot data from API: {e}")
        
        span.set_attribute("sunspot.data_source", source)
        return sun_data, resolved_date_str, city_name

def sunspot_view(request):
    """Main view for sunspot API"""
    # Start a manual span for the entire request processing
    with tracer.start_as_current_span("sunspot.request_processing") as span:
        city_name = None
        lat = None
        lon = None
        source = "api"
        
        city = request.GET.get("city")
        lat_param = request.GET.get("lat")
        lon_param = request.GET.get("lon")
        date_param = request.GET.get("date")
        
        # Add request context to span
        span.set_attribute("http.request.method", request.method)
        span.set_attribute("http.request.path", request.path)
        span.set_attribute("business.query_type", "city" if city else "coordinates")
        span.set_attribute("user_agent", request.META.get('HTTP_USER_AGENT', 'unknown'))
        
        # Case 1: Query by city name
        if city:
            city_name = city.strip()
            span.set_attribute("business.city_query", city_name)
            
            resolved_date_str = resolve_date_param(date_param)
            
            if not resolved_date_str:
                span.set_status(Status(StatusCode.ERROR, "Invalid date parameter"))
                return JsonResponse({"error": "Invalid date parameter"}, status=400)
            
            # First, try to find any cached data for this city and date
            sun_data, cached_lat, cached_lon = get_cached_sunspot_by_city(city_name.lower(), resolved_date_str)
            if sun_data and cached_lat and cached_lon:
                logger.info(f"Found cached data for city: {city_name}")
                source = "cache"
                span.set_attribute("cache.used", True)
                span.set_attribute("cache.strategy", "city_based_lookup")
                span.add_event("cache_hit_city_based")
                
                return JsonResponse({
                    "city": city_name.title(),
                    "latitude": cached_lat,
                    "longitude": cached_lon,
                    "date_requested": resolved_date_str,
                    "sun_data": sun_data,
                    "source": source
                })
            
            # If no cached data, get coordinates and fetch from API
            lat, lon = get_coordinates_from_city(city_name)
            if not lat or not lon:
                span.set_status(Status(StatusCode.ERROR, "City coordinates not found"))
                return JsonResponse({"error": f"Could not find coordinates for city: {city_name}"}, status=404)
            
            sun_data, resolved_date_str, resolved_city_name = get_sunspot(lat, lon, date_param, city_name)
            if sun_data:
                city_name = resolved_city_name
        
        # Case 2: Query by coordinates
        elif lat_param and lon_param:
            span.set_attribute("business.coord_query", f"{lat_param},{lon_param}")
            
            try:
                lat = str(float(lat_param))
                lon = str(float(lon_param))
                
                resolved_date_str = resolve_date_param(date_param)
                if not resolved_date_str:
                    span.set_status(Status(StatusCode.ERROR, "Invalid date parameter"))
                    return JsonResponse({"error": "Invalid date parameter"}, status=400)
                
                # First, try to find cached data by exact coordinates
                sun_data, cached_city = get_cached_sunspot_by_coords(lat, lon, resolved_date_str)
                if sun_data and cached_city:
                    logger.info(f"Found cached data for coordinates: {lat}, {lon}")
                    source = "cache"
                    span.set_attribute("cache.used", True)
                    span.set_attribute("cache.strategy", "coordinate_based_lookup")
                    span.add_event("cache_hit_coordinate_based")
                    
                    return JsonResponse({
                        "city": cached_city.title(),
                        "latitude": lat,
                        "longitude": lon,
                        "date_requested": resolved_date_str,
                        "sun_data": sun_data,
                        "source": source
                    })
                
                # If not in cache, get city name and fetch data
                sun_data, resolved_date_str, city_name = get_sunspot(lat, lon, date_param)
                
            except ValueError:
                span.set_status(Status(StatusCode.ERROR, "Invalid coordinate format"))
                return JsonResponse({"error": "Invalid lat/lon format"}, status=400)
        else:
            span.set_status(Status(StatusCode.ERROR, "Missing required parameters"))
            return JsonResponse({"error": "Missing city or lat/lon"}, status=400)
        
        # Record final outcome
        if sun_data:
            span.set_attribute("business.result", "success")
            span.add_event("sunspot_lookup_completed_successfully")
            return JsonResponse({
                "city": city_name.title() if city_name else f"Location {lat}, {lon}",
                "latitude": lat,
                "longitude": lon,
                "date_requested": resolved_date_str,
                "sun_data": sun_data,
                "source": source
            })
        else:
            span.set_status(Status(StatusCode.ERROR, "Could not retrieve sunspot data"))
            span.set_attribute("business.result", "failure")
            return JsonResponse({"error": "Could not retrieve sunspot data"}, status=503)

def redis_timeout(request):
    """View to deliberately cause a Redis socket timeout."""
    with tracer.start_as_current_span("redis.timeout_test") as span:
        span.set_attribute("test.type", "redis_timeout")
        logger.info("Attempting to cause Redis timeout.")
        
        if not redis_client:
            logger.error("Redis client not initialized.")
            span.set_status(Status(StatusCode.ERROR, "Redis client not available"))
            return JsonResponse({"error": "Redis client not available"}, status=500)

        try:
            # This should exceed the socket_timeout
            redis_client.blpop("nonexistent-key", timeout=5)
            logger.info("Redis responded (unexpectedly)")
            span.add_event("redis_timeout_not_triggered")
            return JsonResponse({"message": "Redis responded"}, status=200)
        except redis.exceptions.TimeoutError:
            logger.error("Redis timeout occurred as expected.")
            span.set_status(Status(StatusCode.ERROR, "Redis timeout occurred"))
            span.add_event("redis_timeout_triggered")
            return JsonResponse({"error": "Redis timeout occurred"}, status=504)
        except Exception as e:
            logger.error(f"Unexpected error in redis_timeout: {str(e)}", exc_info=True)
            span.set_status(Status(StatusCode.ERROR, f"Unexpected error: {str(e)}"))
            return JsonResponse({"error": f"Unexpected error: {str(e)}"}, status=500)

def div_zero(request):
    """View to deliberately cause an unhandled exception (ZeroDivisionError)."""
    with tracer.start_as_current_span("div_zero_test") as span:
        span.set_attribute("test.type", "zero_division_error")
        logger.critical("Deliberately causing a crash (ZeroDivisionError).")
        
        try:
            result = 1 / 0
            return JsonResponse({"message": f"This should not execute: {result}"}, status=200)
        except ZeroDivisionError as e:
            span.set_status(Status(StatusCode.ERROR, f"ZeroDivisionError: {e}"))
            span.set_attribute("error.type", "zero_division")
            span.record_exception(e)
            return JsonResponse({"error": "Division by zero error occurred"}, status=500)

def health_check(request):
    return JsonResponse({"status": "ok"}, status=200)