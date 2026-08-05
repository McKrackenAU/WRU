"""Unit tests for auth helpers (no database required)."""

from app.auth import (
    hash_password,
    is_admin_path,
    is_password_change_allowed_path,
    is_public_path,
    verify_password,
)


def test_password_hash_roundtrip():
    hashed = hash_password("s3cret-pass")
    assert hashed != "s3cret-pass"
    assert verify_password("s3cret-pass", hashed)
    assert not verify_password("wrong", hashed)


def test_public_paths():
    assert is_public_path("/login")
    assert is_public_path("/api/auth/login")
    assert is_public_path("/api/auth/logout")
    assert is_public_path("/static/js/common.js")
    assert not is_public_path("/")
    assert not is_public_path("/api/sites")


def test_admin_paths():
    assert is_admin_path("/admin")
    assert is_admin_path("/admin/users")
    assert is_admin_path("/api/admin/users")
    assert is_admin_path("/api/system")
    assert is_admin_path("/api/import/tracker")
    assert is_admin_path("/api/map/nearmap-key", "PUT")
    assert not is_admin_path("/api/map/nearmap-key", "GET")
    assert is_admin_path("/api/costs/settings", "PUT")
    assert not is_admin_path("/api/costs/settings", "GET")
    assert is_admin_path("/api/costs/rates", "POST")
    assert not is_admin_path("/api/costs/rates", "GET")
    assert not is_admin_path("/api/sites")


def test_password_change_allowed_paths():
    assert is_password_change_allowed_path("/login")
    assert is_password_change_allowed_path("/api/auth/change-password")
    assert not is_password_change_allowed_path("/api/sites")
