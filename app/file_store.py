"""Compress uploaded files on disk and restore originals on download.

Stored blobs are ``WRU1`` + gzip so existing raw uploads stay readable and
user-supplied ``.gz`` files are not mistaken for our wrapper.
"""

from __future__ import annotations

import gzip
import tempfile
from pathlib import Path

MAGIC = b"WRU1"
GZIP_MAGIC = b"\x1f\x8b"


def compress_bytes(content: bytes) -> bytes:
    return MAGIC + gzip.compress(content, compresslevel=6)


def is_wrapped(content: bytes) -> bool:
    return bool(content) and content.startswith(MAGIC)


def decompress_bytes(content: bytes) -> bytes:
    if is_wrapped(content):
        return gzip.decompress(content[len(MAGIC) :])
    return content


def write_stored_bytes(dest: Path, content: bytes) -> tuple[int, str]:
    """Write compressed bytes. Returns (stored_size, encoding)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    packed = compress_bytes(content)
    dest.write_bytes(packed)
    return len(packed), "gzip"


def read_stored_bytes(path: Path) -> bytes:
    if not path.is_file():
        raise FileNotFoundError(path)
    return decompress_bytes(path.read_bytes())


def materialize_original(path: Path) -> tuple[Path, bool]:
    """Return a path to the original bytes.

    If the file is wrapped, writes a temp file (caller must delete).
    """
    raw = path.read_bytes()
    if not is_wrapped(raw):
        return path, False
    tmp = tempfile.NamedTemporaryFile(prefix="wru-doc-", suffix=path.suffix, delete=False)
    tmp.write(decompress_bytes(raw))
    tmp.close()
    return Path(tmp.name), True
