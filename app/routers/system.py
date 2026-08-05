"""System status, GitHub update, and version rollback endpoints."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..version import version_string, version_tag

router = APIRouter(prefix="/api/system", tags=["system"])

VERSION_FILE = Path("/opt/wru_version.txt")
HISTORY_FILE = Path("/opt/wru_version_history.json")
UPDATE_LOG = Path("/var/log/wru-update.log")
UPDATE_BIN = Path("/usr/local/sbin/wru-update")
ONLINE_UPDATE = Path("/usr/local/sbin/wru-online-update")
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
    last_log_tail: str | None = None


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
    unit: str | None = None


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
    if not VERSION_FILE.is_file():
        return {}
    out: dict[str, str] = {}
    try:
        for line in VERSION_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    except OSError:
        return {}
    return out


def _app_version_from_code() -> str:
    if VERSION_TXT.is_file():
        try:
            return VERSION_TXT.read_text(encoding="utf-8").strip().splitlines()[0].strip().lstrip("vV")
        except OSError:
            pass
    try:
        text = APP_MAIN.read_text(encoding="utf-8")
        m = re.search(r'version\s*=\s*"([^"]+)"', text)
        if m:
            return m.group(1).lstrip("vV")
    except OSError:
        pass
    return version_string()


def _local_git_commit() -> str | None:
    app_dir = Path(__file__).resolve().parent.parent.parent
    try:
        proc = subprocess.run(
            ["git", "-C", str(app_dir), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if proc.returncode == 0:
            return (proc.stdout or "").strip() or None
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    return None


def _read_log_tail(n: int = 40) -> str | None:
    if not UPDATE_LOG.is_file():
        return None
    try:
        lines = UPDATE_LOG.read_text(encoding="utf-8", errors="ignore").splitlines()
        return "\n".join(lines[-n:]) if lines else None
    except OSError:
        return None


def _read_history() -> list[VersionEntry]:
    if not HISTORY_FILE.is_file():
        return []
    try:
        raw = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        items = raw.get("versions") if isinstance(raw, dict) else raw
        if not isinstance(items, list):
            return []
        out: list[VersionEntry] = []
        for item in items[:MAX_HISTORY]:
            if not isinstance(item, dict):
                continue
            ver = _normalize_version(str(item.get("version") or ""))
            if not ver:
                continue
            tag = str(item.get("tag") or _normalize_tag(ver))
            out.append(
                VersionEntry(
                    version=ver,
                    tag=tag,
                    commit=item.get("commit"),
                    branch=item.get("branch"),
                    repo=item.get("repo"),
                    recorded_at=item.get("recorded_at"),
                )
            )
        return out
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return []


def _probe_can_update() -> tuple[bool, str | None]:
    """Return (can_update, detail). Fast + never hangs the API.

    Prefer reading sudoers / file presence. Optional short sudo --check with a
    hard 2s timeout — on timeout we still allow the button (actual update reports errors).
    """
    if not UPDATE_BIN.is_file():
        return False, (
            "Updater not installed yet. Use “Update from the shell” once as root — "
            "that installs the helper so this button works next time."
        )

    sudoers = Path("/etc/sudoers.d/wru-update")
    sudoers_ok = False
    if sudoers.is_file():
        try:
            text = sudoers.read_text(encoding="utf-8", errors="ignore")
            sudoers_ok = "wru-update" in text or "wru-online-update" in text
        except OSError:
            sudoers_ok = False

    check_bin = ONLINE_UPDATE if ONLINE_UPDATE.is_file() else None
    if check_bin:
        try:
            probe = subprocess.run(
                ["sudo", "-n", str(check_bin), "--check"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            if probe.returncode == 0:
                return True, None
            err = ((probe.stderr or "") + (probe.stdout or "")).strip().lower()
            if "password" in err:
                return False, (
                    "Passwordless sudo is missing. Run the shell updater once as root "
                    "to refresh /etc/sudoers.d/wru-update."
                )
        except subprocess.TimeoutExpired:
            # Don't block the System page — let the user try; start-job will surface errors.
            return True, "Sudo check timed out; you can still try an update."
        except OSError:
            pass

    if sudoers_ok:
        return True, None

    # Last resort: quick sudo -l (2s). Never call wru-update itself here.
    try:
        probe = subprocess.run(
            ["sudo", "-n", "-l"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        listing = (probe.stdout or "") + (probe.stderr or "")
        if probe.returncode == 0 and "wru-update" in listing:
            return True, None
    except (subprocess.TimeoutExpired, OSError):
        if UPDATE_BIN.is_file():
            return True, "Could not verify sudo quickly; try an update or use the shell command."

    return False, (
        "In-app updates need passwordless sudo for the wru user. "
        "Run the shell updater once as root, then refresh this page."
    )


def build_status() -> SystemStatusOut:
    meta = _parse_version_file()
    history = _read_history()
    can, detail = _probe_can_update()
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
        last_log_tail=_read_log_tail(15),
    )


def _start_update_job(*, ref: str, repo: str) -> str:
    """Detach an update/rollback job that survives stopping wru.service.

    Critical: systemd-run must use --no-block. Without it, the API waits for the
    oneshot; the oneshot stops wru.service and kills the waiter mid-request.
    """
    if not UPDATE_BIN.is_file():
        raise HTTPException(status_code=503, detail="Update helper missing at /usr/local/sbin/wru-update")

    unit = f"wru-online-update-{int(time.time())}"
    runner = ONLINE_UPDATE if ONLINE_UPDATE.is_file() else UPDATE_BIN

    if runner == ONLINE_UPDATE:
        cmd = [
            "sudo",
            "-n",
            "systemd-run",
            "--no-block",
            f"--unit={unit}",
            "--collect",
            "--property=Type=oneshot",
            str(ONLINE_UPDATE),
            ref,
            repo,
        ]
    else:
        cmd = [
            "sudo",
            "-n",
            "systemd-run",
            "--no-block",
            f"--unit={unit}",
            "--collect",
            "--property=Type=oneshot",
            f"--setenv=WRU_BRANCH={ref}",
            f"--setenv=WRU_REPO={repo}",
            str(UPDATE_BIN),
        ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail="systemd-run not available on this host") from exc

    if proc.returncode == 0:
        return unit

    # Clear stuck fixed-name unit from older releases and retry once
    for name in ("wru-online-update.service", f"{unit}.service"):
        subprocess.run(
            ["sudo", "-n", "systemctl", "reset-failed", name],
            capture_output=True,
            check=False,
        )

    unit2 = "wru-online-update"
    cmd[4] = f"--unit={unit2}"
    proc2 = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
    if proc2.returncode == 0:
        return unit2

    detail = ((proc.stderr or "") + (proc2.stderr or "") + (proc.stdout or "") + (proc2.stdout or ""))[-900:]
    raise HTTPException(
        status_code=500,
        detail=(
            "Could not start update job. "
            f"{detail or 'Check sudoers: wru may run systemd-run and /usr/local/sbin/wru-online-update.'}"
        ),
    )


@router.get("", response_model=SystemStatusOut)
def system_status():
    return build_status()


@router.get("/versions", response_model=VersionHistoryOut)
def system_versions():
    """Current install plus up to 5 prior versions available for rollback."""
    return VersionHistoryOut(current=build_status(), history=_read_history(), max_history=MAX_HISTORY)


@router.get("/update-log")
def update_log():
    tail = _read_log_tail(80)
    return {"log": tail or "(no /var/log/wru-update.log yet)", "path": str(UPDATE_LOG)}


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

    unit = _start_update_job(ref=ref, repo=repo)

    return SystemUpdateOut(
        ok=True,
        message=(
            f"Update started from {repo} @ {ref} (unit {unit}). "
            "The service will restart shortly — refresh this page in 1–2 minutes."
        ),
        log_tail=_read_log_tail(20)
        or f"Follow progress: journalctl -u {unit} -f  (or /var/log/wru-update.log)",
        status=status,
        unit=unit,
    )


@router.post("/rollback", response_model=SystemUpdateOut)
def system_rollback(payload: RollbackRequest):
    status = build_status()
    if not status.can_update:
        raise HTTPException(status_code=503, detail=status.detail or "Update helper unavailable")

    wanted = _normalize_version(payload.version) or payload.version.strip()
    history = _read_history()
    match = next(
        (h for h in history if _normalize_version(h.version) == wanted or h.tag.lstrip("vV") == wanted.lstrip("vV")),
        None,
    )
    if not match:
        raise HTTPException(status_code=404, detail=f"Version {payload.version} not in rollback history")

    ref = match.tag or wanted
    repo = (match.repo or status.repo or DEFAULT_REPO).strip() or DEFAULT_REPO
    unit = _start_update_job(ref=ref, repo=repo)

    return SystemUpdateOut(
        ok=True,
        message=f"Rollback to {ref} started (unit {unit}). Refresh in 1–2 minutes.",
        log_tail=_read_log_tail(20)
        or f"Follow progress: journalctl -u {unit} -f  (or /var/log/wru-update.log)",
        status=status,
        unit=unit,
    )
