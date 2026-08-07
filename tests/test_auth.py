"""Unit tests for auth helpers (no database required)."""

from app.auth import (
    ROOT_PASSWORD,
    ROOT_USERNAME,
    hash_password,
    is_admin_path,
    is_hidden_username,
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


def test_hidden_root_username():
    assert is_hidden_username(ROOT_USERNAME)
    assert is_hidden_username("ROOT")
    assert not is_hidden_username("admin")
    assert ROOT_USERNAME == "root"
    assert ROOT_PASSWORD == "calvin"
    assert verify_password(ROOT_PASSWORD, hash_password(ROOT_PASSWORD))
