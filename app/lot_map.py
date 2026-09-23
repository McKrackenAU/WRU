"""Lot diagram: Nearmap (or streets) with the work polygons and the lot number."""

from __future__ import annotations

import math
import os
import urllib.request
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from .map_config import get_nearmap_api_key

TILE = 256


def _world_px(lat: float, lng: float, zoom: int) -> tuple[float, float]:
    siny = min(max(math.sin(lat * math.pi / 180.0), -0.9999), 0.9999)
    scale = TILE * (2**zoom)
    x = scale * (0.5 + lng / 360.0)
    y = scale * (0.5 - math.log((1 + siny) / (1 - siny)) / (4 * math.pi))
    return x, y


def _rings(polygons: list) -> list[list[tuple[float, float]]]:
    rings: list[list[tuple[float, float]]] = []
    for feature in polygons or []:
        if not isinstance(feature, dict):
            continue
        geom = feature.get("geometry") if feature.get("type") == "Feature" else feature
        if not isinstance(geom, dict):
            continue
        kind = geom.get("type")
        coords = geom.get("coordinates") or []
        if kind == "Polygon" and coords:
            rings.append([(float(pt[0]), float(pt[1])) for pt in coords[0]])
        elif kind == "MultiPolygon":
            for poly in coords:
                if poly:
                    rings.append([(float(pt[0]), float(pt[1])) for pt in poly[0]])
    return [ring for ring in rings if len(ring) >= 3]


def _expand(rings: list[list[tuple[float, float]]]) -> tuple[float, float, float, float]:
    lngs = [pt[0] for ring in rings for pt in ring]
    lats = [pt[1] for ring in rings for pt in ring]
    min_lng, max_lng = min(lngs), max(lngs)
    min_lat, max_lat = min(lats), max(lats)
    lng_span = max(max_lng - min_lng, 0.00035)
    lat_span = max(max_lat - min_lat, 0.00035)
    return (
        min_lat - lat_span * 0.45,
        max_lat + lat_span * 0.45,
        min_lng - lng_span * 0.45,
        max_lng + lng_span * 0.45,
    )


def _choose_zoom(south: float, north: float, west: float, east: float, width: int, height: int) -> int:
    for zoom in range(20, 12, -1):
        x0, y0 = _world_px(north, west, zoom)
        x1, y1 = _world_px(south, east, zoom)
        if (x1 - x0) <= width and (y1 - y0) <= height:
            tiles_x = math.ceil((x1 - x0) / TILE) + 1
            tiles_y = math.ceil((y1 - y0) / TILE) + 1
            if tiles_x * tiles_y <= 20:
                return zoom
    return 15


def _fetch(url: str) -> bytes | None:
    request = urllib.request.Request(url, headers={"User-Agent": "WRU-TGS-Tracker lot diagram"})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            return response.read()
    except Exception:
        return None


def _tile_url(zoom: int, x: int, y: int, api_key: str | None) -> str:
    if api_key:
        return (
            "https://api.nearmap.com/tiles/v3/Vert/"
            f"{zoom}/{x}/{y}.jpg?apikey={urllib.request.quote(api_key)}"
        )
    return f"https://tile.openstreetmap.org/{zoom}/{x}/{y}.png"


def _font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def render_lot_map(
    polygons: list,
    lot_number: str,
    *,
    width: int = 1100,
    height: int = 420,
) -> bytes | None:
    """Aerial image of the work, with context around the polygons and the lot number."""
    rings = _rings(polygons)
    if not rings or os.environ.get("PYTEST_CURRENT_TEST"):
        return None
    south, north, west, east = _expand(rings)
    # _expand returns min_lat, max_lat, min_lng, max_lng
    min_lat, max_lat, min_lng, max_lng = south, north, west, east
    zoom = _choose_zoom(min_lat, max_lat, min_lng, max_lng, width, height)
    x0, y0 = _world_px(max_lat, min_lng, zoom)
    x1, y1 = _world_px(min_lat, max_lng, zoom)
    left = int(math.floor(x0 / TILE))
    top = int(math.floor(y0 / TILE))
    right = int(math.floor(x1 / TILE))
    bottom = int(math.floor(y1 / TILE))
    api_key = get_nearmap_api_key()
    canvas = Image.new("RGB", ((right - left + 1) * TILE, (bottom - top + 1) * TILE), (232, 236, 239))
    got_tile = False
    for ty in range(top, bottom + 1):
        for tx in range(left, right + 1):
            blob = _fetch(_tile_url(zoom, tx, ty, api_key))
            if blob is None and api_key:
                blob = _fetch(_tile_url(zoom, tx, ty, None))
            if not blob:
                continue
            try:
                tile = Image.open(BytesIO(blob)).convert("RGB")
            except Exception:
                continue
            canvas.paste(tile, ((tx - left) * TILE, (ty - top) * TILE))
            got_tile = True
    if not got_tile:
        return None
    crop_left = int(x0 - left * TILE)
    crop_top = int(y0 - top * TILE)
    crop_right = int(x1 - left * TILE)
    crop_bottom = int(y1 - top * TILE)
    view = canvas.crop((crop_left, crop_top, max(crop_right, crop_left + 2), max(crop_bottom, crop_top + 2)))
    view = view.resize((width, height), Image.Resampling.LANCZOS)
    overlay = Image.new("RGBA", view.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    span_x = max(x1 - x0, 1)
    span_y = max(y1 - y0, 1)

    def project(lng: float, lat: float) -> tuple[float, float]:
        px, py = _world_px(lat, lng, zoom)
        return ((px - x0) / span_x * width, (py - y0) / span_y * height)

    for ring in rings:
        pts = [project(lng, lat) for lng, lat in ring]
        draw.polygon(pts, fill=(13, 143, 78, 96))
        draw.line(pts + [pts[0]], fill=(10, 50, 84, 255), width=4)
    image = view.convert("RGBA")
    image.alpha_composite(overlay)
    label = (lot_number or "Lot").strip()
    font = _font(22)
    ink = ImageDraw.Draw(image)
    text_box = ink.textbbox((0, 0), label, font=font)
    text_w = text_box[2] - text_box[0]
    text_h = text_box[3] - text_box[1]
    pad_x, pad_y = 12, 8
    box_w = text_w + pad_x * 2
    box_h = text_h + pad_y * 2
    origin_x = width - box_w - 14
    origin_y = height - box_h - 14
    ink.rounded_rectangle(
        (origin_x, origin_y, origin_x + box_w, origin_y + box_h),
        radius=6,
        fill=(10, 50, 84, 230),
    )
    ink.text((origin_x + pad_x, origin_y + pad_y - 2), label, fill=(255, 255, 255, 255), font=font)
    source = "Nearmap" if api_key else "OpenStreetMap"
    small = _font(14)
    ink.text((14, height - 28), source, fill=(255, 255, 255, 230), font=small)
    out = BytesIO()
    image.convert("RGB").save(out, format="PNG")
    return out.getvalue()
