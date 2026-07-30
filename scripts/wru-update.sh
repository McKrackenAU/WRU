#!/usr/bin/env bash
# Copyright (c) 2026 McKrackenAU / WRU
# Pull latest WRU from GitHub and reinstall in place (preserves DB + uploads).
#
# Run as root inside the WRU LXC / VM — any of:
#
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/McKrackenAU/WRU/main/scripts/wru-update.sh)"
#   sudo wru-update
#   WRU_BRANCH=main /usr/local/sbin/wru-update
#
# From the Proxmox HOST (updates an existing CT):
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/McKrackenAU/WRU/main/ct/wru.sh)"
#   → choose "Update existing CT from GitHub"
#
# The web UI (/system) calls this via sudo once the helper is installed.

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
HELPER_BIN="/usr/local/sbin/wru-update"

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
curl -fsSL "${RAW_BASE}/install/wru-install.sh" -o "$tmp"
chmod +x "$tmp"

export WRU_REPO="$APP_GIT" WRU_BRANCH="$APP_BRANCH" WRU_PORT="$APP_PORT"
bash "$tmp"
rm -f "$tmp"

# Always (re)install the in-app / CLI updater helper
if [[ -f "${APP_DIR}/scripts/wru-update.sh" ]]; then
  install -m 755 "${APP_DIR}/scripts/wru-update.sh" "$HELPER_BIN"
else
  curl -fsSL "${RAW_BASE}/scripts/wru-update.sh" -o "$HELPER_BIN"
  chmod 755 "$HELPER_BIN"
fi
cat >/etc/sudoers.d/wru-update <<'EOF'
# Allow WRU service user to pull/install updates from GitHub without a password
wru ALL=(root) NOPASSWD: /usr/local/sbin/wru-update
wru ALL=(root) NOPASSWD: /usr/bin/systemd-run
wru ALL=(root) NOPASSWD: /bin/systemctl reset-failed wru-online-update.service
EOF
chmod 440 /etc/sudoers.d/wru-update
echo "Installed CLI updater: ${HELPER_BIN} (and sudo for user wru)"

commit="unknown"
if command -v git >/dev/null 2>&1 && [[ -d "$APP_DIR/.git" ]]; then
  commit="$(git -C "$APP_DIR" rev-parse --short HEAD 2>/dev/null || echo unknown)"
fi
app_ver="unknown"
if [[ -f "$APP_DIR/app/main.py" ]]; then
  app_ver="$(python3 - <<'PY' 2>/dev/null || echo unknown
import re, pathlib
text = pathlib.Path("/opt/wru/app/main.py").read_text()
m = re.search(r'version\s*=\s*"([^"]+)"', text)
print(m.group(1) if m else "unknown")
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
echo "=== WRU update complete (${app_ver} / ${commit}) ==="
echo "In-app updater: http://$(hostname -I 2>/dev/null | awk '{print $1}'):${APP_PORT}/system"
echo "Next shell update: sudo wru-update"
