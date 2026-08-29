"""Tests for VERSION helpers."""

from app.version import (
    bump_rev,
    channel_label,
    normalize_channel,
    read_raw_version,
    read_repo_channel,
    version_string,
    version_tag,
)


def test_version_file_readable():
    raw = read_raw_version()
    assert raw
    assert version_string() == raw
    assert version_tag() == f"v{raw.lstrip('vV')}"


def test_repo_channel_defaults_to_beta():
    assert read_repo_channel() in {"beta", "stable"}
    assert normalize_channel(None) == "beta"
    assert normalize_channel("STABLE") == "stable"
    assert normalize_channel("nope") == "beta"
    assert channel_label("stable") == "Stable"
    assert channel_label("beta") == "Beta"


def test_bump_rev():
    assert bump_rev("0.1") == "0.2"
    assert bump_rev("0.9") == "0.10"
    assert bump_rev("v0.1") == "0.2"
    assert bump_rev("1.2.3") == "1.2.4"
