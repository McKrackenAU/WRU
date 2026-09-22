"""Live weather via Open-Meteo (no API key)."""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import urlopen

WMO = {
    0: "Clear",
    1: "Mostly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Heavy drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    80: "Rain showers",
    81: "Rain showers",
    82: "Violent rain showers",
    95: "Thunderstorm",
    96: "Thunderstorm with hail",
    99: "Severe thunderstorm",
}


def weather_label(code) -> str:
    try:
        return WMO.get(int(code), f"Code {code}")
    except (TypeError, ValueError):
        return "Unknown"


def fetch_weather(lat: float, lng: float, *, timezone_name: str = "Australia/Melbourne") -> dict:
    params = urlencode(
        {
            "latitude": f"{float(lat):.5f}",
            "longitude": f"{float(lng):.5f}",
            "current": "temperature_2m,weather_code,wind_speed_10m,precipitation,relative_humidity_2m",
            "timezone": timezone_name,
        }
    )
    url = f"https://api.open-meteo.com/v1/forecast?{params}"
    with urlopen(url, timeout=8) as resp:
        raw = resp.read().decode("utf-8")
    import json

    data = json.loads(raw)
    current = data.get("current") or {}
    code = current.get("weather_code")
    snapshot = {
        "lat": float(lat),
        "lng": float(lng),
        "temperature_c": current.get("temperature_2m"),
        "wind_kmh": current.get("wind_speed_10m"),
        "rain_mm": current.get("precipitation"),
        "humidity": current.get("relative_humidity_2m"),
        "code": code,
        "label": weather_label(code),
        "observed_at": current.get("time") or datetime.now(timezone.utc).isoformat(),
        "source": "open-meteo",
    }
    return snapshot
