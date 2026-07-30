"""System status and GitHub update endpoints."""

from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/system", tags=["system"])

VERSION_FILE = Path("/opt/wru_version.txt")
UPDATE_BIN = Path("/usr/local/sbin/wru-update")
APP_MAIN = Path(__file__).resolve().parent.parent / "main.py"
DEFAULT_REPO = os.environ.get("WRU_REPO", "https://github.com/McKrackenAU/WRU.git")
DEFAULT_BRANCH = os.environ.get("WRU_BRANCH", "main")


class SystemStatusOut(BaseModel):
    app_version: str
    branch: str
    repo: str
    commit: str | None = None
    updated_at: str | None = None
    update_available_via: str
    can_update: bool
    detail: str | None = None


class SystemUpdateRequest(BaseModel):
    branch: str | None = Field(default=None, max_length=128)
    repo: str | None = Field(default=None, max_length=512)


class SystemUpdateOut(BaseModel):
    ok: bool
    message: str
    log_tail: str | None = None
    status: SystemStatusOut | None = None


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
        text = APP_MAIN.read_text(encoding="utf-8")
        m = re.search(r'version\s*=\s*"([^"]+)"', text)
        if m:
            return m.group(1)
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


def build_status() -> SystemStatusOut:
    meta = _parse_version_file()
    can = UPDATE_BIN.is_file() and os.access(UPDATE_BIN, os.X_OK)
    detail = None
    if not can:
        detail = (
            "Update helper not installed. Re-run install/wru-install.sh "
            "or place /usr/local/sbin/wru-update (sudo-enabled for user wru)."
        )
    return SystemStatusOut(
        app_version=meta.get("app_version") or _app_version_from_code(),
        branch=meta.get("branch") or DEFAULT_BRANCH,
        repo=meta.get("repo") or DEFAULT_REPO,
        commit=meta.get("commit") or _local_git_commit(),
        updated_at=meta.get("updated_at"),
        update_available_via="sudo /usr/local/sbin/wru-update",
        can_update=can,
        detail=detail,
    )


@router.get("", response_model=SystemStatusOut)
def system_status():
    return build_status()


@router.post("/update", response_model=SystemUpdateOut)
def system_update(payload: SystemUpdateRequest | None = None):
    """Start a GitHub pull/reinstall. Runs detached so the service can restart."""
    status = build_status()
    if not status.can_update:
        raise HTTPException(status_code=503, detail=status.detail or "Update helper unavailable")

    payload = payload or SystemUpdateRequest()
    branch = (payload.branch or status.branch or DEFAULT_BRANCH).strip() or DEFAULT_BRANCH
    repo = (payload.repo or status.repo or DEFAULT_REPO).strip() or DEFAULT_REPO

    # Prefer systemd-run so the job survives stopping wru.service
    cmd = [
        "sudo",
        "-n",
        "systemd-run",
        "--unit=wru-online-update",
        "--collect",
        "--property=Type=oneshot",
        f"--setenv=WRU_BRANCH={branch}",
        f"--setenv=WRU_REPO={repo}",
        str(UPDATE_BIN),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
    except FileNotFoundError:
        # Fallback: detached sleep+update so this HTTP response can return first
        try:
            subprocess.Popen(
                [
                    "sudo",
                    "-n",
                    "/bin/bash",
                    "-c",
                    f"sleep 2; WRU_BRANCH={branch!r} WRU_REPO={repo!r} exec {UPDATE_BIN}",
                ],
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            proc = None
        except OSError as exc:
            raise HTTPException(status_code=503, detail=f"Could not start update: {exc}") from exc

    if proc is not None and proc.returncode != 0:
        # systemd-run may fail if a previous unit is lingering — try reset + retry once
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

    return SystemUpdateOut(
        ok=True,
        message=(
            f"Update started from {repo} @ {branch}. "
            "The service will restart shortly — refresh this page in 1–2 minutes."
        ),
        log_tail="Follow progress: journalctl -u wru-online-update -f  (or /var/log/wru-update.log)",
        status=status,
    )
