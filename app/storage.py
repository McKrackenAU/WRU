"""Document file locations, compression, and archive moves.

Live files sit in the app data dir (`uploads/`). Archived site files sit in
`uploads/archived/`. Directories are created on first use, never at import.
"""

from __future__ import annotations

import gzip
import io
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .database import ARCHIVE_DIR, DATA_DIR, UPLOAD_DIR, ensure_dir

GZIP_MAGIC = b"\x1f\x8b"
JPEG_MAGIC = b"\xff\xd8"
ZIP_MAGIC = b"PK"
PNG_MAGIC = b"\x89PNG"
PDF_MAGIC = b"%PDF"

# Already compressed containers — gzip rarely saves space.
SKIP_GZIP_SUFFIXES = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".zip",
    ".gz",
    ".bz2",
    ".xz",
    ".7z",
    ".rar",
    ".mp3",
    ".mp4",
    ".mov",
    ".avi",
    ".mkv",
    ".ogg",
    ".woff",
    ".woff2",
    ".xlsx",
    ".xlsm",
    ".docx",
    ".pptx",
}

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
MIN_GZIP_BYTES = 512
GZIP_SAVE_RATIO = 0.92  # keep gzip only when the file shrinks by 8%+
JPEG_QUALITY = 80
IMAGE_MAX_EDGE = 3600


@dataclass(frozen=True)
class StoredBlob:
    data: bytes
    encoding: str  # plain | gzip
    logical_size: int
    stored_size: int
    content_type: str | None


def upload_dir() -> Path:
    return ensure_dir(UPLOAD_DIR)


def archive_dir() -> Path:
    return ensure_dir(ARCHIVE_DIR)


def data_dir() -> Path:
    return ensure_dir(DATA_DIR)


def estimate_dir(*, archived: bool = False) -> Path:
    root = archive_dir() if archived else upload_dir()
    path = root / "cost-estimates"
    return ensure_dir(path)


def _archive_is_inside_uploads() -> bool:
    try:
        archive_dir().resolve().relative_to(upload_dir().resolve())
        return True
    except ValueError:
        return False


def _recompress_image(content: bytes, suffix: str, content_type: str | None) -> tuple[bytes, str | None]:
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return content, content_type
    try:
        im = Image.open(io.BytesIO(content))
        im = ImageOps.exif_transpose(im)
    except Exception:
        return content, content_type

    max_edge = IMAGE_MAX_EDGE
    if max(im.size) > max_edge:
        im.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)

    out = io.BytesIO()
    kind = suffix.lower()
    try:
        if kind in {".jpg", ".jpeg"}:
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            im.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
            ctype = "image/jpeg"
        elif kind == ".png":
            im.save(out, format="PNG", optimize=True)
            ctype = "image/png"
        elif kind == ".webp":
            im.save(out, format="WEBP", quality=JPEG_QUALITY, method=4)
            ctype = "image/webp"
        else:
            return content, content_type
    except Exception:
        return content, content_type
    data = out.getvalue()
    if not data or len(data) >= len(content):
        return content, content_type
    return data, ctype or content_type


def compress_document(
    content: bytes,
    filename: str,
    content_type: str | None = None,
) -> StoredBlob:
    """Shrink an upload for disk. Downloads always get the logical (usable) bytes."""
    if not content:
        return StoredBlob(data=b"", encoding="plain", logical_size=0, stored_size=0, content_type=content_type)
    suffix = Path(filename or "").suffix.lower()
    logical = content
    ctype = content_type
    if suffix in IMAGE_SUFFIXES:
        logical, ctype = _recompress_image(content, suffix, content_type)

    encoding = "plain"
    stored = logical
    skip = suffix in SKIP_GZIP_SUFFIXES
    if not skip and logical.startswith((JPEG_MAGIC, PNG_MAGIC, ZIP_MAGIC, GZIP_MAGIC)):
        skip = True
    if not skip and len(logical) >= MIN_GZIP_BYTES:
        packed = gzip.compress(logical, compresslevel=6)
        if packed and len(packed) < int(len(logical) * GZIP_SAVE_RATIO):
            stored = packed
            encoding = "gzip"
    return StoredBlob(
        data=stored,
        encoding=encoding,
        logical_size=len(logical),
        stored_size=len(stored),
        content_type=ctype,
    )


def decode_stored_bytes(data: bytes, encoding: str | None) -> bytes:
    kind = (encoding or "plain").strip().lower()
    if kind == "gzip" or data.startswith(GZIP_MAGIC):
        try:
            return gzip.decompress(data)
        except (OSError, EOFError) as exc:
            if kind == "gzip":
                raise ValueError("Stored document is not valid gzip") from exc
    return data


def stored_encoding(doc: Any) -> str:
    return (getattr(doc, "stored_encoding", None) or "plain").strip().lower() or "plain"


def candidate_document_paths(stored_name: str, *, subdir: str = "") -> list[Path]:
    name = (stored_name or "").strip()
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        return []
    rel = Path(subdir) / name if subdir else Path(name)
    live = upload_dir() / rel
    archived = archive_dir() / rel
    if live.resolve() == archived.resolve():
        return [live]
    return [live, archived]


def resolve_stored_path(stored_name: str, *, subdir: str = "", prefer_archive: bool = False) -> Path:
    paths = candidate_document_paths(stored_name, subdir=subdir)
    if not paths:
        raise FileNotFoundError("Invalid stored filename")
    ordered = list(reversed(paths)) if prefer_archive else paths
    for path in ordered:
        if path.is_file():
            return path
    return ordered[0]


def write_blob(dest: Path, blob: StoredBlob) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(blob.data)


def read_document_bytes(doc: Any, *, prefer_archive: bool = False, subdir: str = "") -> bytes:
    path = resolve_stored_path(
        getattr(doc, "stored_name", ""),
        prefer_archive=prefer_archive,
        subdir=subdir,
    )
    if not path.is_file():
        raise FileNotFoundError(path)
    return decode_stored_bytes(path.read_bytes(), stored_encoding(doc))


def stored_payload(doc: Any, *, prefer_archive: bool = False, subdir: str = "") -> tuple[Path | None, bytes | None]:
    """Return (path, None) for uncompressed files, or (None, logical_bytes) when gzipped."""
    path = resolve_stored_path(
        getattr(doc, "stored_name", ""),
        prefer_archive=prefer_archive,
        subdir=subdir,
    )
    if not path.is_file():
        raise FileNotFoundError(path)
    if stored_encoding(doc) == "gzip":
        return None, decode_stored_bytes(path.read_bytes(), "gzip")
    return path, None


def unlink_stored_file(stored_name: str, *, subdir: str = "") -> None:
    for path in candidate_document_paths(stored_name, subdir=subdir):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _move_named_file(stored_name: str, *, subdir: str = "", to_archive: bool) -> None:
    name = (stored_name or "").strip()
    if not name:
        return
    src_root = upload_dir() if to_archive else archive_dir()
    dst_root = archive_dir() if to_archive else upload_dir()
    src = (src_root / subdir / name) if subdir else (src_root / name)
    dst = (dst_root / subdir / name) if subdir else (dst_root / name)
    if not src.is_file():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() == dst.resolve():
        return
    shutil.move(str(src), str(dst))


def relocate_site_files(db: Any, site_id: int, *, archived: bool) -> None:
    """Move a site's documents (and cost attachments) between live and archive disks."""
    from .models import CostEstimate, CostEstimateAttachment, Document

    docs = db.query(Document).filter(Document.site_id == int(site_id)).all()
    for doc in docs:
        _move_named_file(doc.stored_name, to_archive=archived)
    estimates = db.query(CostEstimate).filter(CostEstimate.site_id == int(site_id)).all()
    ids = [e.id for e in estimates]
    if not ids:
        return
    atts = (
        db.query(CostEstimateAttachment)
        .filter(CostEstimateAttachment.estimate_id.in_(ids))
        .all()
    )
    for att in atts:
        _move_named_file(att.stored_name, subdir="cost-estimates", to_archive=archived)
