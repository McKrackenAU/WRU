#!/usr/bin/env bash
# Copyright (c) 2026 McKrackenAU / WRU
# Pull WRU from GitHub (branch or version tag) and reinstall in place (preserves DB + uploads).
#
# Run as root inside the WRU LXC / VM — any of:
#
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/McKrackenAU/WRU/main/scripts/wru-update.sh)"
#   sudo wru-update
#   WRU_BRANCH=main /usr/local/sbin/wru-update
#   WRU_BRANCH=v0.1 /usr/local/sbin/wru-update   # install / roll back to a tagged release
#
# From the Proxmox HOST (updates an existing CT):
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/McKrackenAU/WRU/main/ct/wru.sh)"
#   → choose "Update existing CT from GitHub"
#
# The web UI (/system) calls this via sudo once the helper is installed.
# Before each install, the current version is saved to /opt/wru_version_history.json
# (max 5 prior entries) so the app can roll back.

set -euo pipefail

APP="WRU TGS Tracker"
APP_DIR="/opt/wru"
APP_GIT="${WRU_REPO:-https://github.com/McKrackenAU/WRU.git}"
APP_BRANCH="${WRU_BRANCH:-main}"
APP_PORT="${WRU_PORT:-8000}"
RAW_BASE="${WRU_RAW_BASE:-https://raw.githubusercontent.com/McKrackenAU/WRU/${APP_BRANCH}}"
LOCK_FILE="/var/lock/wru-update.lock"
LOG_FILE="/var/log/wru-update.log"
VERSION_FILE="/opt/wru_version.txt"
HISTORY_FILE="/opt/wru_version_history.json"
HELPER_BIN="/usr/local/sbin/wru-update"
MAX_HISTORY=5

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Must run as root (or via sudo)." >&2
  echo "  sudo bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/McKrackenAU/WRU/main/scripts/wru-update.sh)\"" >&2
  exit 1
fi

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "Another WRU update is already running." >&2
  exit 2
fi

mkdir -p "$(dirname "$LOG_FILE")"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "=== WRU update $(date -Is) ==="
echo "Repo: ${APP_GIT}  Ref: ${APP_BRANCH}"

# Prefer env from installed service
if [[ -f /etc/default/wru ]]; then
  # shellcheck disable=SC1091
  set -a
  # shellcheck disable=SC1091
  source /etc/default/wru
  set +a
  APP_PORT="${WRU_PORT:-$APP_PORT}"
fi

snapshot_current_version() {
  # Record the currently installed version before replacing it (max 5).
  python3 - <<'PY'
import json, os, re
from datetime import datetime, timezone
from pathlib import Path

version_file = Path("/opt/wru_version.txt")
history_file = Path("/opt/wru_version_history.json")
app_dir = Path("/opt/wru")
max_history = 5

meta = {}
if version_file.is_file():
    for line in version_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            meta[k.strip()] = v.strip()

ver = (meta.get("app_version") or "").strip().lstrip("vV")
if not ver and (app_dir / "VERSION").is_file():
    try:
        ver = (app_dir / "VERSION").read_text(encoding="utf-8").strip().splitlines()[0].strip().lstrip("vV")
    except Exception:
        ver = ""
if not ver and (app_dir / "app" / "main.py").is_file():
    try:
        text = (app_dir / "app" / "main.py").read_text(encoding="utf-8")
        m = re.search(r'version\s*=\s*"([^"]+)"', text)
        if m:
            ver = m.group(1).lstrip("vV")
    except Exception:
        pass
if not ver:
    raise SystemExit(0)

commit = meta.get("commit")
if not commit and (app_dir / ".git").is_dir():
    import subprocess
    try:
        commit = subprocess.check_output(
            ["git", "-C", str(app_dir), "rev-parse", "--short", "HEAD"],
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        commit = None

entry = {
    "version": ver,
    "tag": f"v{ver}",
    "commit": commit,
    "branch": meta.get("branch"),
    "repo": meta.get("repo"),
    "recorded_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
}

history = []
if history_file.is_file():
    try:
        raw = json.loads(history_file.read_text(encoding="utf-8"))
        items = raw.get("versions") if isinstance(raw, dict) else raw
        if isinstance(items, list):
            history = [i for i in items if isinstance(i, dict)]
    except Exception:
        history = []

# Drop duplicate of the version we're about to re-record at the front
history = [i for i in history if str(i.get("version") or "").lstrip("vV") != ver]
history.insert(0, entry)
history = history[:max_history]
history_file.write_text(json.dumps({"versions": history}, indent=2) + "\n", encoding="utf-8")
os.chmod(history_file, 0o644)
print(f"Recorded prior version v{ver} in history ({len(history)}/{max_history})")
PY
}

if [[ -d "$APP_DIR" ]]; then
  snapshot_current_version || true
  systemctl stop wru 2>/dev/null || true
fi

tmp="$(mktemp)"
# Prefer install script from the target ref; fall back to main if ref is brand-new
if ! curl -fsSL "${RAW_BASE}/install/wru-install.sh" -o "$tmp"; then
  echo "Could not fetch install script from ref ${APP_BRANCH}; trying main…"
  curl -fsSL "https://raw.githubusercontent.com/McKrackenAU/WRU/main/install/wru-install.sh" -o "$tmp"
fi
chmod +x "$tmp"

export WRU_REPO="$APP_GIT" WRU_BRANCH="$APP_BRANCH" WRU_PORT="$APP_PORT"
bash "$tmp"
rm -f "$tmp"

# Always (re)install the in-app / CLI updater helper
if [[ -f "${APP_DIR}/scripts/wru-update.sh" ]]; then
  install -m 755 "${APP_DIR}/scripts/wru-update.sh" "$HELPER_BIN"
else
  curl -fsSL "${RAW_BASE}/scripts/wru-update.sh" -o "$HELPER_BIN" \
    || curl -fsSL "https://raw.githubusercontent.com/McKrackenAU/WRU/main/scripts/wru-update.sh" -o "$HELPER_BIN"
  chmod 755 "$HELPER_BIN"
fi
# Minimal LXCs may lack sudo /etc/sudoers.d
apt-get install -y sudo >/dev/null 2>&1 || true
mkdir -p /etc/sudoers.d
if [[ -f /etc/sudoers ]] && ! grep -qE '^[@#]includedir[[:space:]]+/etc/sudoers\.d' /etc/sudoers; then
  printf '\n#includedir /etc/sudoers.d\n' >>/etc/sudoers
fi
cat >/etc/sudoers.d/wru-update <<'EOF'
# Allow WRU service user to pull/install updates from GitHub without a password
wru ALL=(root) NOPASSWD: /usr/local/sbin/wru-update
wru ALL=(root) NOPASSWD: /usr/bin/systemd-run
wru ALL=(root) NOPASSWD: /bin/systemctl reset-failed wru-online-update.service
EOF
chmod 440 /etc/sudoers.d/wru-update
if command -v visudo >/dev/null 2>&1 && ! visudo -cf /etc/sudoers.d/wru-update >/dev/null 2>&1; then
  echo "Warning: sudoers file invalid — removed" >&2
  rm -f /etc/sudoers.d/wru-update
else
  echo "Installed CLI updater: ${HELPER_BIN} (and sudo for user wru)"
fi

commit="unknown"
if command -v git >/dev/null 2>&1 && [[ -d "$APP_DIR/.git" ]]; then
  commit="$(git -C "$APP_DIR" rev-parse --short HEAD 2>/dev/null || echo unknown)"
fi
app_ver="unknown"
if [[ -f "$APP_DIR/VERSION" ]]; then
  app_ver="$(tr -d '[:space:]' <"$APP_DIR/VERSION" | sed 's/^v//')"
elif [[ -f "$APP_DIR/app/main.py" ]]; then
  app_ver="$(python3 - <<'PY' 2>/dev/null || echo unknown
import re, pathlib
text = pathlib.Path("/opt/wru/app/main.py").read_text()
m = re.search(r'version\s*=\s*"([^"]+)"', text)
print(m.group(1).lstrip("vV") if m else "unknown")
PY
)"
fi
{
  echo "branch=${APP_BRANCH}"
  echo "repo=${APP_GIT}"
  echo "app_version=${app_ver}"
  echo "version_tag=v${app_ver}"
  echo "updated_at=$(date -Is)"
  echo "commit=${commit}"
} >"$VERSION_FILE"
chmod 644 "$VERSION_FILE"

systemctl start wru 2>/dev/null || true
echo "=== WRU update complete (v${app_ver} / ${commit}) ==="
echo "In-app updater: http://$(hostname -I 2>/dev/null | awk '{print $1}'):${APP_PORT}/system"
echo "Next shell update: sudo wru-update"
echo "Rollback (example): WRU_BRANCH=v0.1 sudo wru-update"
