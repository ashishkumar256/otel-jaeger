import json 
import time 
import logging 
from datetime import date, timedelta 
import redis 
import requests 
from dateutil import parser 
from django.conf import settings 
from django.http import JsonResponse 

logger = logging.getLogger("sunspot")

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
    today = date.today()
    if not date_param or date_param.lower() == 'today':
        return today.strftime('%Y-%m-%d')
    elif date_param.lower() == 'yesterday':
        return (today - timedelta(days=1)).strftime('%Y-%m-%d')
    elif date_param.lower() == 'tomorrow':
        return (today + timedelta(days=1)).strftime('%Y-%m-%d')
    else:
        try:
            return parser.parse(date_param).strftime('%Y-%m-%d')
        except ValueError:
            return None

def get_coordinates_from_city(city):
    """Get latitude and longitude from city name using Nominatim"""
    try:
        response = requests.get(
            settings.NOMINATIM_SEARCH_URL,
            params={"city": city, "format": "json", "limit": 1},
            headers={"User-Agent": "SunspotMinimal/1.0"}
        )
        response.raise_for_status()
        data = response.json()
        if data and data[0].get("lat") and data[0].get("lon"):
            return data[0]["lat"], data[0]["lon"]
    except Exception as e:
        logger.warning(f"Error fetching coordinates for city '{city}': {e}")
    return None, None

def get_city_from_coordinates(lat, lon):
    """Get city name from coordinates using Nominatim reverse geocoding"""
    try:
        response = requests.get(
            settings.NOMINATIM_REVERSE_URL,
            params={"lat": lat, "lon": lon, "format": "json"},
            headers={"User-Agent": "SunspotMinimal/1.0"}
        )
        response.raise_for_status()
        data = response.json()
        address = data.get("address", {})
        return (
            address.get("city") or 
            address.get("town") or 
            address.get("village") or 
            address.get("hamlet") or 
            data.get("display_name", f"Location {lat}, {lon}")
        )
    except Exception as e:
        logger.warning(f"Error reverse geocoding {lat}, {lon}: {e}")
        return f"Location {lat}, {lon}"

def get_cached_city_coordinates(city_name):
    """Get cached coordinates for a city"""
    if not redis_client:
        return None, None
    
    cache_key = f"{settings.REDIS_KEY_PREFIX}:city_coords:{city_name.lower()}"
    cached_data = redis_client.get(cache_key)
    
    if cached_data:
        try:
            coords = json.loads(cached_data)
            return coords.get("lat"), coords.get("lon")
        except json.JSONDecodeError:
            logger.warning(f"Error decoding cached coordinates for city: {city_name}")
    
    return None, None

def cache_city_coordinates(city_name, lat, lon):
    """Cache city coordinates with longer TTL"""
    if redis_client:
        cache_key = f"{settings.REDIS_KEY_PREFIX}:city_coords:{city_name.lower()}"
        coords_data = {"lat": lat, "lon": lon}
        # Longer TTL for city coordinates (e.g., 1 week)
        city_ttl = getattr(settings, "CITY_CACHE_TTL", 604800)  # 7 days
        redis_client.set(cache_key, json.dumps(coords_data), ex=city_ttl)
        logger.info(f"Cached city coordinates for {city_name}")

def get_cached_sunspot_by_city(city_name, date_str):
    """Get any cached sunspot data for a city (any coordinates within that city)"""
    if not redis_client:
        return None
    
    # Search for any cached data for this city and date
    pattern = f"{settings.REDIS_KEY_PREFIX}:data:{city_name.lower()}:*:{date_str}"
    keys = redis_client.keys(pattern)
    
    if keys:
        # Return the first matching cached data
        cached_data = redis_client.get(keys[0])
        if cached_data:
            try:
                return json.loads(cached_data)
            except json.JSONDecodeError:
                logger.warning("Error decoding cached sunspot data")
    
    return None

def get_sunspot(lat, lon, date_param, city_name=None):
    """Get sunspot data from API or cache with enhanced city-based caching"""
    resolved_date_str = resolve_date_param(date_param)
    if not resolved_date_str:
        return None, None
    
    # If city_name is provided, try to get cached data for any coordinates in that city
    if city_name and redis_client:
        cached_sun_data = get_cached_sunspot_by_city(city_name, resolved_date_str)
        if cached_sun_data:
            logger.info(f"City cache HIT for {city_name} on {resolved_date_str}")
            return cached_sun_data, resolved_date_str
    
    # Primary cache key with exact coordinates
    cache_key = f"{settings.REDIS_KEY_PREFIX}:data:{lat}:{lon}:{resolved_date_str}"
    
    # Secondary cache key with city information (if available)
    city_cache_key = None
    if city_name:
        city_cache_key = f"{settings.REDIS_KEY_PREFIX}:data:{city_name.lower()}:{lat}:{lon}:{resolved_date_str}"
    
    ttl = settings.CACHE_TTL
    sun_data = None
    
    # Try to get from primary cache
    if redis_client:
        cached_data = redis_client.get(cache_key)
        if cached_data:
            logger.info(f"Primary cache HIT for key: {cache_key}")
            try:
                sun_data = json.loads(cached_data)
            except json.JSONDecodeError:
                logger.warning("Error decoding cached data, fetching from API.")
                sun_data = None
    
    # Fetch from API if not in cache
    if sun_data is None:
        logger.info(f"Cache MISS, fetching from API for coordinates {lat}, {lon}")
        try:
            params = {"lat": lat, "lng": lon, "date": resolved_date_str}
            response = requests.get(settings.SUNRISE_SUNSET_API_URL, params=params)
            response.raise_for_status()
            data = response.json()
            
            if data.get("status") == "OK":
                sun_data = data["results"]
                
                # Cache the result with multiple keys
                if sun_data and redis_client:
                    # Primary cache with coordinates only
                    redis_client.set(cache_key, json.dumps(sun_data), ex=ttl)
                    logger.info(f"Primary cache SET for key: {cache_key}")
                    
                    # Secondary cache with city information (if available)
                    if city_cache_key:
                        redis_client.set(city_cache_key, json.dumps(sun_data), ex=ttl)
                        logger.info(f"Secondary cache SET for key: {city_cache_key}")
                        
        except Exception as e:
            logger.error(f"Error fetching sunspot data from API: {e}")
    
    return sun_data, resolved_date_str

def sunspot_view(request):
    """Main view for sunspot API with enhanced caching"""
    city_name = None
    city = request.GET.get("city")
    lat = request.GET.get("lat")
    lon = request.GET.get("lon")
    date_param = request.GET.get("date")
    
    if city:
        city_name = city.strip()
        # First try to get cached coordinates for the city
        cached_lat, cached_lon = get_cached_city_coordinates(city_name)
        
        if cached_lat and cached_lon:
            logger.info(f"Using cached coordinates for city: {city_name}")
            lat, lon = cached_lat, cached_lon
        else:
            # Fetch new coordinates and cache them
            lat, lon = get_coordinates_from_city(city_name)
            if lat and lon:
                cache_city_coordinates(city_name, lat, lon)
                logger.info(f"Cached new coordinates for city: {city_name}")
            else:
                return JsonResponse({"error": f"Could not find coordinates for city: {city_name}"}, status=404)
    
    elif lat and lon:
        try:
            lat = str(float(lat))
            lon = str(float(lon))
            # Get city name from coordinates for caching
            city_name = get_city_from_coordinates(lat, lon)
        except ValueError:
            return JsonResponse({"error": "Invalid lat/lon format"}, status=400)
    else:
        return JsonResponse({"error": "Missing city or lat/lon"}, status=400)
    
    # Get sunspot data with enhanced caching
    sun_data, resolved_date_str = get_sunspot(lat, lon, date_param, city_name)
    
    if sun_data:
        return JsonResponse({
            "city": city_name,
            "latitude": lat,
            "longitude": lon,
            "date_requested": resolved_date_str,
            "sun_data": sun_data,
            "cache_strategy": "enhanced_city_caching"
        })
    else:
        return JsonResponse({"error": "Could not retrieve sunspot data or invalid date parameter"}, status=503)

def health_check(request):
    return JsonResponse({"status": "ok"}, status=200)