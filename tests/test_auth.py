"""Unit tests for auth helpers (no database required)."""

from app.auth import (
    ROOT_PASSWORD,
    ROOT_USERNAME,
    hash_password,
    is_admin_path,
    is_hidden_username,
    is_password_change_allowed_path,
    is_public_path,
    new_password_error,
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
    assert is_public_path("/manifest.webmanifest")
    assert is_public_path("/sw.js")
    assert is_public_path("/api/live/version")
    assert is_public_path("/health")
    assert not is_public_path("/api/live/revision")
    assert not is_public_path("/")
    assert not is_public_path("/api/sites")
    assert not is_public_path("/password")
    assert not is_public_path("/api/auth/change-password")


def test_password_change_allowed_paths():
    assert is_password_change_allowed_path("/password")
    assert is_password_change_allowed_path("/api/auth/me")
    assert is_password_change_allowed_path("/api/auth/change-password")
    assert is_password_change_allowed_path("/api/auth/logout")
    assert is_password_change_allowed_path("/static/js/password.js")
    assert is_password_change_allowed_path("/sw.js")
    assert is_password_change_allowed_path("/manifest.webmanifest")
    assert not is_password_change_allowed_path("/")
    assert not is_password_change_allowed_path("/api/sites")
    assert not is_password_change_allowed_path("/admin/users")


def test_new_password_error():
    assert new_password_error("short") == "New password must be at least 8 characters"
    assert new_password_error("same-pass", "same-pass") == "New password must be different from the current password"
    assert new_password_error("good-enough", "old-secret") is None


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
