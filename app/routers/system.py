"""System status, GitHub update, and version rollback endpoints."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import require_admin
from ..version import version_string, version_tag

router = APIRouter(
    prefix="/api/system",
    tags=["system"],
    dependencies=[Depends(require_admin)],
)

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


class CheckUpdateRequest(BaseModel):
    branch: str | None = Field(default=None, max_length=128)
    repo: str | None = Field(default=None, max_length=512)


class CheckUpdateOut(BaseModel):
    ok: bool
    update_available: bool
    current_version: str
    current_tag: str
    remote_version: str | None = None
    remote_tag: str | None = None
    remote_ref: str
    repo: str
    current_commit: str | None = None
    remote_commit: str | None = None
    detail: str


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
            "The updater isn't installed on this server yet. "
            "Ask whoever set up WRU to finish the install, then hit Refresh."
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
                    "This server isn't allowed to update from the app yet. "
                    "Ask whoever set up WRU to finish the updater setup, then hit Refresh."
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
            return True, "Could not verify updater permission quickly; you can still try an update."

    return False, (
        "In-app updates aren't ready on this server yet. "
        "Ask whoever set up WRU to finish the updater setup, then hit Refresh."
    )


def _parse_github_slug(repo_url: str) -> tuple[str, str] | None:
    """Return (owner, repo) from a GitHub URL, or None if not parseable."""
    raw = (repo_url or "").strip()
    if not raw:
        return None
    if raw.startswith("git@"):
        # git@github.com:Owner/Repo.git
        m = re.match(r"git@[^:]+:([^/]+)/([^/]+?)(?:\.git)?$", raw)
        if m:
            return m.group(1), m.group(2)
        return None
    try:
        parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if host not in {"github.com", "www.github.com"}:
        return None
    parts = [p for p in (parsed.path or "").strip("/").split("/") if p]
    if len(parts) < 2:
        return None
    owner, name = parts[0], parts[1]
    if name.endswith(".git"):
        name = name[: -len(".git")]
    return owner, name


def _http_get_text(url: str, *, timeout: float = 10.0, accept: str = "*/*") -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "WRU-TGS-Tracker-Updater",
            "Accept": accept,
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — fixed GitHub hosts only
        return resp.read().decode("utf-8", errors="replace")


def _version_parts(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in _normalize_version(value).split("."):
        if not chunk:
            continue
        m = re.match(r"(\d+)", chunk)
        parts.append(int(m.group(1)) if m else 0)
    return tuple(parts) or (0,)


def _cmp_versions(a: str, b: str) -> int:
    """-1 if a < b, 0 if equal, 1 if a > b."""
    ta, tb = _version_parts(a), _version_parts(b)
    n = max(len(ta), len(tb))
    ta = ta + (0,) * (n - len(ta))
    tb = tb + (0,) * (n - len(tb))
    if ta < tb:
        return -1
    if ta > tb:
        return 1
    return 0


def _fetch_remote_version(owner: str, repo: str, ref: str) -> str:
    """Read VERSION for a branch/tag/SHA.

    Prefer the GitHub Contents API (pinned to ``ref``) so we don't get a stale
    ``raw.githubusercontent.com`` CDN body that disagrees with the tip commit.
    """
    api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/VERSION?ref={ref}"
    try:
        text = _http_get_text(
            api_url,
            timeout=10.0,
            accept="application/vnd.github.raw",
        )
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        text = _http_get_text(
            f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/VERSION",
            timeout=10.0,
        )
    line = text.strip().splitlines()[0].strip() if text.strip() else ""
    if not line:
        raise ValueError("Remote VERSION file is empty")
    return _normalize_version(line)


def _fetch_remote_commit(owner: str, repo: str, ref: str) -> str | None:
    """Return the full tip commit SHA for ``ref``, or None."""
    url = f"https://api.github.com/repos/{owner}/{repo}/commits/{ref}"
    try:
        raw = _http_get_text(url, timeout=10.0, accept="application/vnd.github+json")
        data = json.loads(raw)
        sha = data.get("sha")
        return str(sha) if sha else None
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, ValueError):
        return None


def _is_real_commit(value: str | None) -> bool:
    raw = (value or "").strip().lower()
    if not raw or raw in {"unknown", "none", "null", "n/a", "-"}:
        return False
    # short or full hex sha
    return bool(re.fullmatch(r"[0-9a-f]{7,40}", raw))


def check_for_update(*, branch: str, repo: str, current: SystemStatusOut) -> CheckUpdateOut:
    slug = _parse_github_slug(repo)
    if not slug:
        raise HTTPException(
            status_code=400,
            detail="Repository must be a GitHub URL (e.g. https://github.com/McKrackenAU/WRU.git)",
        )
    owner, name = slug
    ref = (branch or DEFAULT_BRANCH).strip() or DEFAULT_BRANCH

    # Resolve tip SHA first, then read VERSION at that SHA (avoids branch CDN skew).
    remote_sha = _fetch_remote_commit(owner, name, ref)
    remote_commit = remote_sha[:7] if remote_sha else None
    version_ref = remote_sha or ref

    try:
        remote_ver = _fetch_remote_version(owner, name, version_ref)
    except urllib.error.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Could not read VERSION from GitHub ({ref}): HTTP {exc.code}",
        ) from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Could not reach GitHub to check for updates: {exc}",
        ) from exc

    remote_tag = _normalize_tag(remote_ver)
    current_ver = _normalize_version(current.app_version) or current.app_version
    current_tag = current.version_tag or _normalize_tag(current_ver)
    cmp = _cmp_versions(current_ver, remote_ver)

    update_available = False
    if cmp < 0:
        update_available = True
        detail = f"Update available: {remote_tag} on {ref} (you’re on {current_tag})."
        if remote_commit:
            detail += f" Tip {remote_commit}."
    elif cmp > 0:
        detail = f"You’re ahead of {ref}: local {current_tag}, remote {remote_tag}."
    else:
        # Same VERSION number — only compare commits when both look like real SHAs.
        # Local "unknown" used to false-trigger “newer commit” while CDN still showed
        # the previous VERSION.
        cur_c = (current.commit or "").strip().lower()
        rem_c = (remote_commit or "").strip().lower()
        if (
            _is_real_commit(cur_c)
            and _is_real_commit(rem_c)
            and not (cur_c.startswith(rem_c) or rem_c.startswith(cur_c))
        ):
            update_available = True
            detail = (
                f"Same version {remote_tag}, but {ref} has a newer commit "
                f"({remote_commit} vs local {current.commit})."
            )
        elif not _is_real_commit(cur_c) and remote_commit:
            detail = (
                f"You’re on {current_tag} (matches {ref}). "
                f"Local commit is unknown — tip is {remote_commit}. "
                f"Pull & install if you want to refresh install metadata."
            )
            # Don't mark update_available solely because commit metadata is missing
            update_available = False
        else:
            detail = f"You’re up to date — {current_tag} matches {ref}."
            if remote_commit:
                detail += f" Tip {remote_commit}."

    return CheckUpdateOut(
        ok=True,
        update_available=update_available,
        current_version=current_ver,
        current_tag=current_tag,
        remote_version=remote_ver,
        remote_tag=remote_tag,
        remote_ref=ref,
        repo=repo,
        current_commit=current.commit,
        remote_commit=remote_commit,
        detail=detail,
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


@router.post("/check-update", response_model=CheckUpdateOut)
def system_check_update(payload: CheckUpdateRequest | None = None):
    """Compare the installed VERSION with the selected GitHub branch/tag (no install)."""
    status = build_status()
    payload = payload or CheckUpdateRequest()
    ref = (payload.branch or status.branch or DEFAULT_BRANCH).strip() or DEFAULT_BRANCH
    repo = (payload.repo or status.repo or DEFAULT_REPO).strip() or DEFAULT_REPO
    return check_for_update(branch=ref, repo=repo, current=status)


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
