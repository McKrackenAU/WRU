#!/usr/bin/env bash
# Copyright (c) 2026 McKrackenAU / WRU
# Pull latest WRU from GitHub and reinstall in place (preserves DB + uploads).
#
# Intended to run as root on the WRU host/LXC:
#   /usr/local/sbin/wru-update
#   WRU_BRANCH=main /usr/local/sbin/wru-update
#
# The web UI calls this via sudo from the wru service user.

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

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Must run as root (or via sudo)." >&2
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
echo "Repo: ${APP_GIT}  Branch: ${APP_BRANCH}"

# Prefer env from installed service
if [[ -f /etc/default/wru ]]; then
  # shellcheck disable=SC1091
  set -a
  # shellcheck disable=SC1091
  source /etc/default/wru
  set +a
  APP_PORT="${WRU_PORT:-$APP_PORT}"
fi

if [[ -d "$APP_DIR" ]]; then
  systemctl stop wru 2>/dev/null || true
fi

tmp="$(mktemp)"
if [[ -f "${APP_DIR}/install/wru-install.sh" ]]; then
  # Use checkout's install script after clone — fetch from GitHub first for reliability
  curl -fsSL "${RAW_BASE}/install/wru-install.sh" -o "$tmp" || cp "${APP_DIR}/install/wru-install.sh" "$tmp"
else
  curl -fsSL "${RAW_BASE}/install/wru-install.sh" -o "$tmp"
fi
chmod +x "$tmp"

export WRU_REPO="$APP_GIT" WRU_BRANCH="$APP_BRANCH" WRU_PORT="$APP_PORT"
bash "$tmp"
rm -f "$tmp"

# Record version metadata
commit="unknown"
if command -v git >/dev/null 2>&1 && [[ -d "$APP_DIR/.git" ]]; then
  commit="$(git -C "$APP_DIR" rev-parse --short HEAD 2>/dev/null || echo unknown)"
elif [[ -d "$APP_DIR" ]]; then
  # Shallow clone may be wiped; try reading from a marker written by install
  :
fi
# Install script does wipe .git with depth clone then mv — capture from clone by rewriting install
# Fall back to app version file + timestamp
app_ver="1.3.0"
if [[ -f "$APP_DIR/app/main.py" ]]; then
  app_ver="$(python3 - <<'PY' 2>/dev/null || echo 1.3.0
import re, pathlib
text = pathlib.Path("/opt/wru/app/main.py").read_text()
m = re.search(r'version\s*=\s*"([^"]+)"', text)
print(m.group(1) if m else "1.3.0")
PY
)"
fi
{
  echo "branch=${APP_BRANCH}"
  echo "repo=${APP_GIT}"
  echo "app_version=${app_ver}"
  echo "updated_at=$(date -Is)"
  echo "commit=${commit}"
} >"$VERSION_FILE"
chmod 644 "$VERSION_FILE"

systemctl start wru 2>/dev/null || true
echo "=== WRU update complete ==="
