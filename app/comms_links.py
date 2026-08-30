"""Validate comms resource links (SharePoint and other https URLs)."""

from __future__ import annotations

from urllib.parse import urlparse


def normalize_resource_url(raw: str) -> str:
    url = (raw or "").strip()
    if not url:
        raise ValueError("Link is required")
    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http:// and https:// links are allowed")
    host = (parsed.hostname or "").strip().rstrip(".")
    if not host or "." not in host:
        raise ValueError("Enter a full web address")
    if parsed.username or parsed.password:
        raise ValueError("Links cannot include a username or password")
    return url[:2000]
