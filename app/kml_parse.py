from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any


NS = {
    "kml": "http://www.opengis.net/kml/2.2",
    "gx": "http://www.google.com/kml/ext/2.2",
}


def _strip_ns(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _parse_coords(text: str | None) -> list[list[float]]:
    if not text:
        return []
    points: list[list[float]] = []
    for token in text.replace("\n", " ").split():
        parts = token.split(",")
        if len(parts) < 2:
            continue
        try:
            lon = float(parts[0])
            lat = float(parts[1])
        except ValueError:
            continue
        points.append([lon, lat])
    return points


def _geometry_from_element(el: ET.Element) -> dict[str, Any] | None:
    tag = _strip_ns(el.tag)
    if tag == "Point":
        coords = _parse_coords(el.findtext("kml:coordinates", default=None, namespaces=NS) or el.findtext("coordinates"))
        if not coords:
            return None
        return {"type": "Point", "coordinates": coords[0]}
    if tag == "LineString":
        coords = _parse_coords(el.findtext("kml:coordinates", default=None, namespaces=NS) or el.findtext("coordinates"))
        if len(coords) < 2:
            return None
        return {"type": "LineString", "coordinates": coords}
    if tag == "Polygon":
        rings = []
        for ring in el.findall(".//kml:LinearRing", NS) or el.findall(".//LinearRing"):
            coords = _parse_coords(
                ring.findtext("kml:coordinates", default=None, namespaces=NS)
                or ring.findtext("coordinates")
            )
            if coords:
                rings.append(coords)
        if not rings:
            return None
        return {"type": "Polygon", "coordinates": rings}
    if tag == "MultiGeometry":
        geoms = []
        for child in list(el):
            g = _geometry_from_element(child)
            if g:
                geoms.append(g)
        if not geoms:
            return None
        if len(geoms) == 1:
            return geoms[0]
        return {"type": "GeometryCollection", "geometries": geoms}
    # recurse into unknown wrappers
    for child in list(el):
        g = _geometry_from_element(child)
        if g:
            return g
    return None


def _placemark_props(pm: ET.Element) -> dict[str, Any]:
    props: dict[str, Any] = {}
    for data in pm.findall(".//kml:SimpleData", NS) + pm.findall(".//SimpleData"):
        key = data.attrib.get("name") or "value"
        props[key] = (data.text or "").strip()
    for data in pm.findall(".//kml:Data", NS) + pm.findall(".//Data"):
        key = data.attrib.get("name") or "value"
        val = data.findtext("kml:value", default=None, namespaces=NS) or data.findtext("value")
        props[key] = (val or "").strip()
    return props


def parse_kml_features(content: bytes) -> list[dict[str, Any]]:
    """Return feature dicts: name, description, geometry, properties."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ValueError(f"Invalid KML: {exc}") from exc

    placemarks = root.findall(".//kml:Placemark", NS) or root.findall(".//Placemark")
    features: list[dict[str, Any]] = []
    for pm in placemarks:
        name = (
            pm.findtext("kml:name", default=None, namespaces=NS)
            or pm.findtext("name")
            or ""
        ).strip()
        description = (
            pm.findtext("kml:description", default=None, namespaces=NS)
            or pm.findtext("description")
            or ""
        ).strip()
        geometry = None
        for child in list(pm):
            geometry = _geometry_from_element(child)
            if geometry:
                break
        if not geometry:
            continue
        props = _placemark_props(pm)
        features.append(
            {
                "name": name or props.get("Name") or props.get("name") or "Untitled",
                "description": description,
                "geometry": geometry,
                "properties": props,
            }
        )
    return features
