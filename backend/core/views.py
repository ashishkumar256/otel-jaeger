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
            params={"q": city, "format": "json", "limit": 1},
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
        city_name = (
            address.get("city") or 
            address.get("town") or 
            address.get("village") or 
            address.get("hamlet") or 
            "Unknown"
        )
        return city_name
    except Exception as e:
        logger.warning(f"Error reverse geocoding {lat}, {lon}: {e}")
        return "Unknown"

def get_cached_sunspot_by_city(city_name, date_str):
    """Get any cached sunspot data for a city (any coordinates within that city)"""
    if not redis_client:
        return None, None, None
    
    # Search for any cached data for this city and date
    pattern = f"{settings.REDIS_KEY_PREFIX}:{city_name.lower()}:*:{date_str}"
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
                return sun_data, cached_lat, cached_lon
            except (json.JSONDecodeError, IndexError) as e:
                logger.warning(f"Error decoding cached sunspot data: {e}")
    
    return None, None, None

def get_cached_sunspot_by_coords(lat, lon, date_str):
    """Get cached sunspot data by exact coordinates"""
    if not redis_client:
        return None, None
    
    # Search for cached data with these exact coordinates
    pattern = f"{settings.REDIS_KEY_PREFIX}:*:{lat}:{lon}:{date_str}"
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
                return sun_data, cached_city
            except (json.JSONDecodeError, IndexError) as e:
                logger.warning(f"Error decoding cached data: {e}")
    
    return None, None

def get_sunspot(lat, lon, date_param, city_name=None):
    """Get sunspot data from API or cache"""
    resolved_date_str = resolve_date_param(date_param)
    if not resolved_date_str:
        return None, None, None
    
    ttl = settings.CACHE_TTL
    sun_data = None
    
    # If city_name is not provided, get it from coordinates
    if not city_name:
        city_name = get_city_from_coordinates(lat, lon)
    
    # Create cache key with city:lat:lon:date format
    cache_key = f"{settings.REDIS_KEY_PREFIX}:{city_name.lower()}:{lat}:{lon}:{resolved_date_str}"
    
    # Try to get from cache first
    if redis_client:
        cached_data = redis_client.get(cache_key)
        if cached_data:
            logger.info(f"Cache HIT for key: {cache_key}")
            try:
                sun_data = json.loads(cached_data)
                return sun_data, resolved_date_str, city_name
            except json.JSONDecodeError:
                logger.warning("Error decoding cached data, fetching from API.")
                sun_data = None
    
    # Fetch from API if not in cache
    if sun_data is None:
        logger.info(f"Cache MISS, fetching from API for key: {cache_key}")
        try:
            params = {"lat": lat, "lng": lon, "date": resolved_date_str}
            response = requests.get(settings.SUNRISE_SUNSET_API_URL, params=params)
            response.raise_for_status()
            data = response.json()
            
            if data.get("status") == "OK":
                sun_data = data["results"]
                
                # Cache the result
                if sun_data and redis_client:
                    redis_client.set(cache_key, json.dumps(sun_data), ex=ttl)
                    logger.info(f"Cache SET for key: {cache_key} with TTL: {ttl}s")
                        
        except Exception as e:
            logger.error(f"Error fetching sunspot data from API: {e}")
    
    return sun_data, resolved_date_str, city_name

def sunspot_view(request):
    """Main view for sunspot API"""
    city_name = None
    lat = None
    lon = None
    source = "api"
    
    city = request.GET.get("city")
    lat_param = request.GET.get("lat")
    lon_param = request.GET.get("lon")
    date_param = request.GET.get("date")
    
    # Case 1: Query by city name
    if city:
        city_name = city.strip()
        resolved_date_str = resolve_date_param(date_param)
        
        if not resolved_date_str:
            return JsonResponse({"error": "Invalid date parameter"}, status=400)
        
        # First, try to find any cached data for this city and date
        sun_data, cached_lat, cached_lon = get_cached_sunspot_by_city(city_name.lower(), resolved_date_str)
        if sun_data and cached_lat and cached_lon:
            logger.info(f"Found cached data for city: {city_name}")
            source = "cache"
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
            return JsonResponse({"error": f"Could not find coordinates for city: {city_name}"}, status=404)
        
        sun_data, resolved_date_str, resolved_city_name = get_sunspot(lat, lon, date_param, city_name)
        if sun_data:
            city_name = resolved_city_name
    
    # Case 2: Query by coordinates
    elif lat_param and lon_param:
        try:
            lat = str(float(lat_param))
            lon = str(float(lon_param))
            
            resolved_date_str = resolve_date_param(date_param)
            if not resolved_date_str:
                return JsonResponse({"error": "Invalid date parameter"}, status=400)
            
            # First, try to find cached data by exact coordinates
            sun_data, cached_city = get_cached_sunspot_by_coords(lat, lon, resolved_date_str)
            if sun_data and cached_city:
                logger.info(f"Found cached data for coordinates: {lat}, {lon}")
                source = "cache"
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
            return JsonResponse({"error": "Invalid lat/lon format"}, status=400)
    else:
        return JsonResponse({"error": "Missing city or lat/lon"}, status=400)
    
    if sun_data:
        return JsonResponse({
            "city": city_name.title() if city_name else f"Location {lat}, {lon}",
            "latitude": lat,
            "longitude": lon,
            "date_requested": resolved_date_str,
            "sun_data": sun_data,
            "source": source
        })
    else:
        return JsonResponse({"error": "Could not retrieve sunspot data"}, status=503)

def health_check(request):
    return JsonResponse({"status": "ok"}, status=200)