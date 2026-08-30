"""Beta / Stable release channel for the system updater."""

import json
from pathlib import Path

from app.routers import system as system_mod
from app.version import channel_label, normalize_channel, read_repo_channel

ROOT = Path(__file__).resolve().parent.parent


def test_channel_file_is_beta_or_stable():
    raw = (ROOT / "CHANNEL").read_text(encoding="utf-8").strip().splitlines()[0].strip()
    assert raw.lower() in {"beta", "stable"}
    assert read_repo_channel() == normalize_channel(raw)
    assert channel_label("beta") == "Beta"
    assert channel_label("stable") == "Stable"


def test_unknown_commit_is_hidden():
    assert system_mod._display_commit(None) is None
    assert system_mod._display_commit("unknown") is None
    assert system_mod._display_commit("n/a") is None
    assert system_mod._display_commit("056cb6f") == "056cb6f"


def test_channel_override_is_version_scoped(tmp_path, monkeypatch):
    monkeypatch.setattr(system_mod, "DATA_DIR", tmp_path)
    system_mod._write_channel_override("1.95", "stable")
    assert system_mod._read_channel_override("1.95") == "stable"
    assert system_mod._read_channel_override("1.96") is None
    system_mod._write_channel_override("1.96", "beta")
    assert system_mod._read_channel_override("1.95") == "stable"
    payload = json.loads((tmp_path / "release_channel.json").read_text(encoding="utf-8"))
    assert payload == {"channels": {"1.95": "stable", "1.96": "beta"}}


def test_legacy_single_override_still_reads(tmp_path, monkeypatch):
    monkeypatch.setattr(system_mod, "DATA_DIR", tmp_path)
    (tmp_path / "release_channel.json").write_text(
        json.dumps({"version": "1.99", "channel": "stable"}), encoding="utf-8"
    )
    assert system_mod._read_channel_override("1.99") == "stable"
    assert system_mod._read_channel_override("2.0") is None


def test_history_uses_stored_stable_mark(tmp_path, monkeypatch):
    monkeypatch.setattr(system_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(system_mod, "HISTORY_FILE", tmp_path / "wru_version_history.json")
    (tmp_path / "wru_version_history.json").write_text(
        json.dumps({"versions": [{"version": "1.99", "tag": "v1.99", "channel": "beta"}]}),
        encoding="utf-8",
    )
    rows = system_mod._read_history()
    assert rows[0].channel == "beta"
    system_mod._write_channel_override("1.99", "stable")
    system_mod._write_history_channel("1.99", "stable")
    rows = system_mod._read_history()
    assert rows[0].channel == "stable"
    assert rows[0].channel_label == "Stable"
    stored = json.loads((tmp_path / "wru_version_history.json").read_text(encoding="utf-8"))
    assert stored["versions"][0]["channel"] == "stable"


def test_resolve_channel_prefers_override(tmp_path, monkeypatch):
    monkeypatch.setattr(system_mod, "DATA_DIR", tmp_path)
    meta = {"channel": "beta"}
    assert system_mod._resolve_channel(meta, "1.95") == "beta"
    system_mod._write_channel_override("1.95", "stable")
    assert system_mod._resolve_channel(meta, "1.95") == "stable"


def test_system_ui_exposes_channel_controls():
    html = (ROOT / "app/static/system.html").read_text(encoding="utf-8")
    js = (ROOT / "app/static/js/system.js").read_text(encoding="utf-8")
    py = (ROOT / "app/routers/system.py").read_text(encoding="utf-8")
    assert 'id="btnMarkStable"' in html
    assert "/api/system/channel" in js
    assert '@router.put("/channel"' in py
    assert "channel=${channel}" in (ROOT / "scripts/wru-update.sh").read_text(encoding="utf-8")
    assert "release_channel.json" in (ROOT / "scripts/wru-update.sh").read_text(encoding="utf-8")
