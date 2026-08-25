"""Raise Starlette multipart part limits so uploads are not capped at 1 MB."""

from __future__ import annotations

from starlette.formparsers import MultiPartParser

# Match the largest upload we accept (KML 50 MB). File parts themselves are
# spooled to disk; this mainly covers non-file form fields and older Starlette
# builds that applied the cap to files as well.
MULTIPART_MAX_BYTES = 50 * 1024 * 1024


def configure_multipart_limits() -> None:
    MultiPartParser.max_part_size = MULTIPART_MAX_BYTES
    MultiPartParser.max_file_size = MULTIPART_MAX_BYTES
