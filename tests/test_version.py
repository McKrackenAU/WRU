"""Tests for VERSION helpers."""

from app.version import bump_rev, read_raw_version, version_string, version_tag


def test_version_starts_at_0_1():
    assert read_raw_version() == "0.1"
    assert version_string() == "0.1"
    assert version_tag() == "v0.1"


def test_bump_rev():
    assert bump_rev("0.1") == "0.2"
    assert bump_rev("0.9") == "0.10"
    assert bump_rev("v0.1") == "0.2"
    assert bump_rev("1.2.3") == "1.2.4"
