"""System status, GitHub update, and version rollback endpoints."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..version import version_string, version_tag

router = APIRouter(prefix="/api/system", tags=["system"])

VERSION_FILE = Path("/opt/wru_version.txt")
HISTORY_FILE = Path("/opt/wru_version_history.json")
UPDATE_BIN = Path("/usr/local/sbin/wru-update")
APP_MAIN = Path(__file__).resolve().parent.parent / "main.py"
VERSION_TXT = Path(__file__).resolve().parent.parent.parent / "VERSION"
DEFAULT_REPO = os.environ.get("WRU_REPO", "https://github.com/McKrackenAU/WRU.git")
DEFAULT_BRANCH = os.environ.get("WRU_BRANCH", "main")
MAX_HISTORY = 5


class SystemStatusOut(BaseModel):
    app_version: str
    version_tag: str
    branch: str
    repo: str
    commit: str | None = None
    updated_at: str | None = None
    update_available_via: str
    can_update: bool
    can_rollback: bool
    detail: str | None = None
    shell_ct: str | None = None
    shell_proxmox: str | None = None


class VersionEntry(BaseModel):
    version: str
    tag: str
    commit: str | None = None
    branch: str | None = None
    repo: str | None = None
    recorded_at: str | None = None


class VersionHistoryOut(BaseModel):
    current: SystemStatusOut
    history: list[VersionEntry]
    max_history: int = MAX_HISTORY


class SystemUpdateRequest(BaseModel):
    branch: str | None = Field(default=None, max_length=128)
    repo: str | None = Field(default=None, max_length=512)
    version: str | None = Field(default=None, max_length=64)


class SystemUpdateOut(BaseModel):
    ok: bool
    message: str
    log_tail: str | None = None
    status: SystemStatusOut | None = None


class RollbackRequest(BaseModel):
    version: str = Field(..., min_length=1, max_length=64)


SHELL_CT = (
    'bash -c "$(curl -fsSL https://raw.githubusercontent.com/McKrackenAU/WRU/main/scripts/wru-update.sh)"'
)
SHELL_PROXMOX = (
    'bash -c "$(curl -fsSL https://raw.githubusercontent.com/McKrackenAU/WRU/main/ct/wru.sh)"'
    "  # then choose: Update existing CT from GitHub"
)


def _normalize_tag(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    return raw if raw.startswith("v") or raw.startswith("V") else f"v{raw.lstrip('vV')}"


def _normalize_version(value: str) -> str:
    return (value or "").strip().lstrip("vV")


def _parse_version_file() -> dict[str, str]:
    data: dict[str, str] = {}
    if not VERSION_FILE.is_file():
        return data
    for line in VERSION_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        data[k.strip()] = v.strip()
    return data


def _app_version_from_code() -> str:
    try:
        if VERSION_TXT.is_file():
            return VERSION_TXT.read_text(encoding="utf-8").strip().splitlines()[0].strip().lstrip("vV")
    except (OSError, IndexError):
        pass
    try:
        return version_string()
    except Exception:
        pass
    try:
        text = APP_MAIN.read_text(encoding="utf-8")
        m = re.search(r'version\s*=\s*"([^"]+)"', text)
        if m:
            return m.group(1).lstrip("vV")
    except OSError:
        pass
    return "unknown"


def _local_git_commit() -> str | None:
    app_dir = Path("/opt/wru")
    if not (app_dir / ".git").is_dir():
        return None
    try:
        out = subprocess.check_output(
            ["git", "-C", str(app_dir), "rev-parse", "--short", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return out.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _read_history() -> list[VersionEntry]:
    if not HISTORY_FILE.is_file():
        return []
    try:
        raw = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = raw.get("versions") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return []
    out: list[VersionEntry] = []
    for item in items[:MAX_HISTORY]:
        if not isinstance(item, dict):
            continue
        ver = _normalize_version(str(item.get("version") or item.get("tag") or ""))
        if not ver:
            continue
        tag = _normalize_tag(str(item.get("tag") or ver))
        out.append(
            VersionEntry(
                version=ver,
                tag=tag,
                commit=item.get("commit"),
                branch=item.get("branch"),
                repo=item.get("repo"),
                recorded_at=item.get("recorded_at") or item.get("updated_at"),
            )
        )
    return out[:MAX_HISTORY]


def build_status() -> SystemStatusOut:
    meta = _parse_version_file()
    can = UPDATE_BIN.is_file() and os.access(UPDATE_BIN, os.X_OK)
    history = _read_history()
    detail = None
    if not can:
        detail = (
            "In-app updater helper not installed yet. Run the shell command below "
            "once as root inside this CT (or use Proxmox host → Update existing CT). "
            "That installs /usr/local/sbin/wru-update for future UI updates."
        )
    app_ver = meta.get("app_version") or _app_version_from_code()
    app_ver = _normalize_version(app_ver) or app_ver
    return SystemStatusOut(
        app_version=app_ver,
        version_tag=_normalize_tag(app_ver) if app_ver and app_ver != "unknown" else version_tag(),
        branch=meta.get("branch") or DEFAULT_BRANCH,
        repo=meta.get("repo") or DEFAULT_REPO,
        commit=meta.get("commit") or _local_git_commit(),
        updated_at=meta.get("updated_at"),
        update_available_via="sudo /usr/local/sbin/wru-update" if can else "shell curl one-liner",
        can_update=can,
        can_rollback=can and bool(history),
        detail=detail,
        shell_ct=SHELL_CT,
        shell_proxmox=SHELL_PROXMOX,
    )


def _start_update_job(*, ref: str, repo: str) -> None:
    """Detach an update/rollback job that survives stopping wru.service."""
    cmd = [
        "sudo",
        "-n",
        "systemd-run",
        "--unit=wru-online-update",
        "--collect",
        "--property=Type=oneshot",
        f"--setenv=WRU_BRANCH={ref}",
        f"--setenv=WRU_REPO={repo}",
        str(UPDATE_BIN),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
    except FileNotFoundError:
        try:
            subprocess.Popen(
                [
                    "sudo",
                    "-n",
                    "/bin/bash",
                    "-c",
                    f"sleep 2; WRU_BRANCH={ref!r} WRU_REPO={repo!r} exec {UPDATE_BIN}",
                ],
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return
        except OSError as exc:
            raise HTTPException(status_code=503, detail=f"Could not start update: {exc}") from exc

    if proc.returncode == 0:
        return

    subprocess.run(
        ["sudo", "-n", "systemctl", "reset-failed", "wru-online-update.service"],
        capture_output=True,
        check=False,
    )
    proc2 = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
    if proc2.returncode != 0:
        detail = ((proc.stderr or "") + (proc2.stderr or "") + (proc.stdout or ""))[-800:]
        raise HTTPException(
            status_code=500,
            detail=f"Could not start update job. {detail or 'Check sudoers for wru → wru-update / systemd-run.'}",
        )


@router.get("", response_model=SystemStatusOut)
def system_status():
    return build_status()


@router.get("/versions", response_model=VersionHistoryOut)
def system_versions():
    """Current install plus up to 5 prior versions available for rollback."""
    return VersionHistoryOut(current=build_status(), history=_read_history(), max_history=MAX_HISTORY)


@router.post("/update", response_model=SystemUpdateOut)
def system_update(payload: SystemUpdateRequest | None = None):
    """Start a GitHub pull/reinstall. Runs detached so the service can restart."""
    status = build_status()
    if not status.can_update:
        raise HTTPException(status_code=503, detail=status.detail or "Update helper unavailable")

    payload = payload or SystemUpdateRequest()
    if payload.version:
        ref = _normalize_tag(payload.version)
    else:
        ref = (payload.branch or status.branch or DEFAULT_BRANCH).strip() or DEFAULT_BRANCH
    repo = (payload.repo or status.repo or DEFAULT_REPO).strip() or DEFAULT_REPO

    _start_update_job(ref=ref, repo=repo)

    return SystemUpdateOut(
        ok=True,
        message=(
            f"Update started from {repo} @ {ref}. "
            "The service will restart shortly — refresh this page in 1–2 minutes."
        ),
        log_tail="Follow progress: journalctl -u wru-online-update -f  (or /var/log/wru-update.log)",
        status=status,
    )


@router.post("/rollback", response_model=SystemUpdateOut)
def system_rollback(payload: RollbackRequest):
    """Roll back to a prior release tag (max 5 kept in history)."""
    status = build_status()
    if not status.can_update:
        raise HTTPException(status_code=503, detail=status.detail or "Update helper unavailable")

    wanted = _normalize_tag(payload.version)
    wanted_ver = _normalize_version(payload.version)
    history = _read_history()
    match = next(
        (
            e
            for e in history
            if e.tag == wanted or e.version == wanted_ver or _normalize_tag(e.version) == wanted
        ),
        None,
    )
    if match is None:
        raise HTTPException(
            status_code=404,
            detail=f"Version {wanted} is not in the last {MAX_HISTORY} recorded installs.",
        )

    ref = match.tag or wanted
    repo = (match.repo or status.repo or DEFAULT_REPO).strip() or DEFAULT_REPO
    _start_update_job(ref=ref, repo=repo)

    return SystemUpdateOut(
        ok=True,
        message=(
            f"Rollback to {ref} started. "
            "The service will restart shortly — refresh this page in 1–2 minutes."
        ),
        log_tail="Follow progress: journalctl -u wru-online-update -f  (or /var/log/wru-update.log)",
        status=status,
    )
