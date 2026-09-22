"""Read GeoPackage (.gpkg) layers into GeoJSON features (WC / QGIS export)."""

from __future__ import annotations

import sqlite3
import struct
import tempfile
from pathlib import Path


class _Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.i = 0
        self.le = True

    def remaining(self) -> int:
        return len(self.data) - self.i

    def take(self, n: int) -> bytes:
        if self.remaining() < n:
            raise ValueError("Truncated geometry")
        chunk = self.data[self.i : self.i + n]
        self.i += n
        return chunk

    def u8(self) -> int:
        return self.take(1)[0]

    def u32(self) -> int:
        fmt = "<I" if self.le else ">I"
        return struct.unpack(fmt, self.take(4))[0]

    def f64(self) -> float:
        fmt = "<d" if self.le else ">d"
        return struct.unpack(fmt, self.take(8))[0]


def _wkb_to_geojson(reader: _Reader) -> dict:
    endian = reader.u8()
    reader.le = endian == 1
    raw_type = reader.u32()
    geom_type = raw_type % 1000
    if geom_type == 1:
        return {"type": "Point", "coordinates": [reader.f64(), reader.f64()]}
    if geom_type == 2:
        n = reader.u32()
        return {"type": "LineString", "coordinates": [[reader.f64(), reader.f64()] for _ in range(n)]}
    if geom_type == 3:
        rings = reader.u32()
        coords = []
        for _ in range(rings):
            n = reader.u32()
            coords.append([[reader.f64(), reader.f64()] for _ in range(n)])
        return {"type": "Polygon", "coordinates": coords}
    if geom_type == 6:
        n = reader.u32()
        parts = [_wkb_to_geojson(reader) for _ in range(n)]
        return {"type": "MultiPolygon", "coordinates": [p["coordinates"] for p in parts if p.get("type") == "Polygon"]}
    if geom_type == 4:
        n = reader.u32()
        parts = [_wkb_to_geojson(reader) for _ in range(n)]
        return {"type": "MultiPoint", "coordinates": [p["coordinates"] for p in parts if p.get("type") == "Point"]}
    if geom_type == 5:
        n = reader.u32()
        parts = [_wkb_to_geojson(reader) for _ in range(n)]
        return {
            "type": "MultiLineString",
            "coordinates": [p["coordinates"] for p in parts if p.get("type") == "LineString"],
        }
    raise ValueError(f"Unsupported geometry type {geom_type}")


def gpkg_blob_to_geojson(blob) -> dict | None:
    if not blob:
        return None
    data = bytes(blob)
    if len(data) < 8:
        return None
    if data[:2] == b"GP":
        flags = data[3]
        empty = flags & 1
        if empty:
            return None
        envelope = (flags >> 1) & 7
        le = bool(flags & 0x10)
        envelope_sizes = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}
        header = 8 + envelope_sizes.get(envelope, 0)
        reader = _Reader(data[header:])
        reader.le = le
        return _wkb_to_geojson(reader)
    if data[0] in (0, 1):
        return _wkb_to_geojson(_Reader(data))
    return None


def parse_gpkg_features(content: bytes, *, max_features: int = 5000) -> list[dict]:
    if not content:
        raise ValueError("Empty GeoPackage")
    tmp = Path(tempfile.mkdtemp(prefix="wru-gpkg-")) / "layer.gpkg"
    tmp.write_bytes(content)
    try:
        conn = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            tables = conn.execute(
                "SELECT table_name, identifier FROM gpkg_contents WHERE data_type = 'features'"
            ).fetchall()
            if not tables:
                raise ValueError("No feature tables in this GeoPackage")
            out: list[dict] = []
            for table in tables:
                name = table["table_name"]
                geom_col = conn.execute(
                    "SELECT column_name FROM gpkg_geometry_columns WHERE table_name = ?",
                    (name,),
                ).fetchone()
                geom_name = geom_col["column_name"] if geom_col else "geom"
                cols = [row["name"] for row in conn.execute(f"PRAGMA table_info({name})")]
                prop_cols = [c for c in cols if c != geom_name]
                rows = conn.execute(f"SELECT * FROM {name}").fetchall()
                for row in rows:
                    mapping = dict(row)
                    geom = gpkg_blob_to_geojson(mapping.get(geom_name))
                    if not geom:
                        continue
                    props = {k: mapping[k] for k in prop_cols if mapping.get(k) is not None}
                    label = (
                        props.get("name")
                        or props.get("Name")
                        or props.get("SITE")
                        or props.get("site_number")
                        or props.get("MOA")
                        or table["identifier"]
                        or name
                    )
                    out.append(
                        {
                            "name": str(label),
                            "description": str(props.get("description") or props.get("DESC") or ""),
                            "geometry": geom,
                            "properties": {str(k): (v if isinstance(v, (str, int, float, bool)) else str(v)) for k, v in props.items()},
                        }
                    )
                    if len(out) >= max_features:
                        return out
            return out
        finally:
            conn.close()
    finally:
        try:
            tmp.unlink(missing_ok=True)
            tmp.parent.rmdir()
        except OSError:
            pass
