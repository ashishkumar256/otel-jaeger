import json
import logging
from datetime import date, timedelta

import redis
import requests
from dateutil import parser
from django.conf import settings
from django.http import JsonResponse

logger = logging.getLogger("sunspot")


def initialize_redis_client():
    """Initialize Redis client with connection test"""
    try:
        r = redis.Redis(
            host=settings.REDIS_HOST, 
            port=int(settings.REDIS_PORT), 
            decode_responses=True
        )
        r.ping()
        logger.info(f"Connected to Redis at {settings.REDIS_SERVER}")
        return r
    except Exception as e:
        logger.warning(f"Could not connect to Redis at {settings.REDIS_SERVER}: {e}")
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
            address.get("city") 
            or address.get("town") 
            or address.get("village") 
            or address.get("hamlet") 
            or data.get("display_name", f"Location {lat}, {lon}")
        )
    except Exception as e:
        logger.warning(f"Error reverse geocoding {lat}, {lon}: {e}")
    return f"Location {lat}, {lon}"


def get_sunspot(lat, lon, date_param):
    """Get sunspot data from API or cache"""
    resolved_date_str = resolve_date_param(date_param)
    if not resolved_date_str:
        return None, None

    cache_key = f"{settings.REDIS_KEY_PREFIX}:{lat}:{lon}:{resolved_date_str}"
    is_today = resolved_date_str == date.today().strftime('%Y-%m-%d')
    ttl = settings.SHORT_TTL if is_today else settings.LONG_TTL
    sun_data = None

    # Try to get from cache
    if redis_client:
        cached_data = redis_client.get(cache_key)
        if cached_data:
            logger.info(f"Cache HIT for key: {cache_key}")
            try:
                sun_data = json.loads(cached_data)
            except json.JSONDecodeError:
                logger.warning("Error decoding cached data, fetching from API.")
                sun_data = None

    # Fetch from API if not in cache
    if sun_data is None:
        logger.info(f"Cache MISS or data error, fetching from API for key: {cache_key}")
        try:
            params = {"lat": lat, "lng": lon}
            if date_param:
                params["date"] = date_param
            
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
            
    return sun_data, resolved_date_str


def sunspot_view(request):
    """Main view for sunspot API"""
    city_name = None
    city = request.GET.get("city")
    lat = request.GET.get("lat")
    lon = request.GET.get("lon")
    date_param = request.GET.get("date")

    # Handle city parameter
    if city:
        city_name = city.strip()
        lat, lon = get_coordinates_from_city(city_name)
        if not lat or not lon:
            return JsonResponse(
                {"error": f"Could not find coordinates for city: {city_name}"}, 
                status=404
            )
    
    # Handle lat/lon parameters
    elif lat and lon:
        try:
            lat = str(float(lat))
            lon = str(float(lon))
            city_name = get_city_from_coordinates(lat, lon)
        except ValueError:
            return JsonResponse({"error": "Invalid lat/lon format"}, status=400)
    
    # Missing required parameters
    else:
        return JsonResponse({"error": "Missing city or lat/lon"}, status=400)

    # Get sunspot data
    sun_data, resolved_date_str = get_sunspot(lat, lon, date_param)
    if sun_data:
        if not city_name:
            city_name = f"Location {lat}, {lon}"
            
        return JsonResponse({
            "city": city_name,
            "latitude": lat,
            "longitude": lon,
            "date_requested": resolved_date_str,
            "sun_data": sun_data
        })
    else:
        return JsonResponse(
            {"error": "Could not retrieve sunspot data or invalid date parameter"}, 
            status=503
        )