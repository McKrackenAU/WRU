#!/usr/bin/env bash
# Copyright (c) 2026 McKrackenAU / WRU
# Author: William McClure
# License: Apache-2.0 | https://github.com/McKrackenAU/WRU/blob/main/LICENSE
# Source: https://github.com/McKrackenAU/WRU
#
# Proxmox Helper Scripts–style installer (runs inside Debian/Ubuntu LXC or VM).
# Compatible with community-scripts FUNCTIONS_FILE_PATH when present.
#
# Standalone:
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/McKrackenAU/WRU/main/install/wru-install.sh)"

set -euo pipefail

APP="WRU TGS Tracker"
APP_SLUG="wru"
APP_DIR="/opt/wru"
DATA_DIR="/opt/wru-data"
SERVICE_NAME="wru"
APP_PORT="${WRU_PORT:-8000}"
APP_GIT="${WRU_REPO:-https://github.com/McKrackenAU/WRU.git}"
APP_BRANCH="${WRU_BRANCH:-main}"
APP_USER="wru"
PG_USER="${POSTGRES_USER:-wru}"
PG_DB="${POSTGRES_DB:-wru}"
PG_HOST="${POSTGRES_HOST:-127.0.0.1}"
PG_PORT="${POSTGRES_PORT:-5432}"

# Load community-scripts helpers when provided by ct/*.sh / build.func
if [[ -n "${FUNCTIONS_FILE_PATH:-}" ]]; then
  # shellcheck disable=SC1091
  source /dev/stdin <<<"$FUNCTIONS_FILE_PATH"
  color
  verb_ip6
  catch_errors
  setting_up_container
  network_check
  update_os
else
  # Standalone helper-script style messaging
  YW=$(echo "\033[33m")
  BL=$(echo "\033[36m")
  RD=$(echo "\033[01;31m")
  BGN=$(echo "\033[4;92m")
  GN=$(echo "\033[1;92m")
  DGN=$(echo "\033[32m")
  CL=$(echo "\033[m")
  BFR="\\r\\033[K"
  HOLD="-"
  CM="${GN}✓${CL}"
  CROSS="${RD}✗${CL}"
  INFO="${BL}ℹ${CL}"

  msg_info() {
    local msg="$1"
    echo -ne " ${HOLD} ${YW}${msg}...${CL}"
  }
  msg_ok() {
    local msg="$1"
    echo -e "${BFR} ${CM} ${GN}${msg}${CL}"
  }
  msg_error() {
    local msg="$1"
    echo -e "${BFR} ${CROSS} ${RD}${msg}${CL}"
  }
  msg_warn() {
    local msg="$1"
    echo -e " ${YW}⚠ ${msg}${CL}"
  }

  STD="silent"
  silent() { "$@" >/dev/null 2>&1; }

  catch_errors() {
    set -Eeuo pipefail
    trap 'msg_error "Failed at line $LINENO: $BASH_COMMAND"; exit 1' ERR
  }

  network_check() {
    msg_info "Checking network"
    if ! ping -c 1 -W 3 1.1.1.1 >/dev/null 2>&1 && ! ping -c 1 -W 3 8.8.8.8 >/dev/null 2>&1; then
      msg_error "No network connectivity"
      exit 1
    fi
    msg_ok "Network OK"
  }

  update_os() {
    msg_info "Updating OS"
    $STD apt-get update
    $STD apt-get -y upgrade
    msg_ok "Updated OS"
  }

  setting_up_container() {
    msg_info "Preparing container"
    export DEBIAN_FRONTEND=noninteractive
    msg_ok "Container ready"
  }

  verb_ip6() { :; }
  color() { :; }
  motd_ssh() { :; }
  customize() { :; }
  cleanup_lxc() {
    msg_info "Cleaning up"
    $STD apt-get -y autoremove
    $STD apt-get -y autoclean
    msg_ok "Cleaned up"
  }

  catch_errors
  setting_up_container
  network_check
  update_os
fi

# Ensure $STD works even if install.func defines it differently
if ! declare -F silent >/dev/null 2>&1 && [[ "${STD:-}" == "silent" ]]; then
  silent() { "$@" >/dev/null 2>&1; }
fi
if ! declare -F msg_warn >/dev/null 2>&1; then
  msg_warn() { echo -e " ⚠ ${1}"; }
fi

urlencode() {
  python3 - <<'PY' "$1"
import sys, urllib.parse
print(urllib.parse.quote(sys.argv[1], safe=""))
PY
}

load_existing_pg_password() {
  if [[ -f /etc/default/wru ]]; then
    # shellcheck disable=SC1091
    set -a
    # shellcheck disable=SC1091
    source /etc/default/wru
    set +a
    if [[ -n "${POSTGRES_PASSWORD:-}" ]]; then
      echo "$POSTGRES_PASSWORD"
      return
    fi
  fi
  echo ""
}

msg_info "Installing Dependencies"
$STD apt-get install -y \
  python3 \
  python3-venv \
  python3-pip \
  git \
  curl \
  ca-certificates \
  sudo \
  locales \
  postgresql \
  postgresql-contrib \
  libpq5
$STD apt-get install -y python3-full || true
$STD apt-get install -y libjpeg62-turbo || $STD apt-get install -y libjpeg-turbo8 || true
$STD apt-get install -y zlib1g || true
# Ensure UTF-8 locale so seed/app strings are not forced through ASCII
if ! locale -a 2>/dev/null | grep -qiE '^(C\.UTF-8|en_US\.utf8|en_US\.UTF-8)$'; then
  sed -i 's/^# *en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen 2>/dev/null || true
  echo 'en_US.UTF-8 UTF-8' >>/etc/locale.gen 2>/dev/null || true
  $STD locale-gen en_US.UTF-8 || true
fi
export LANG="${LANG:-C.UTF-8}"
export LC_ALL="${LC_ALL:-C.UTF-8}"
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
msg_ok "Installed Dependencies"

ensure_postgres_running() {
  msg_info "Starting PostgreSQL"
  systemctl enable -q postgresql 2>/dev/null || true
  systemctl start postgresql 2>/dev/null || service postgresql start 2>/dev/null || true

  local ready=0
  local _
  for _ in $(seq 1 60); do
    if su -s /bin/bash postgres -c "psql -tAc 'SELECT 1'" >/dev/null 2>&1; then
      ready=1
      break
    fi
    # Older / clustered layouts
    if systemctl start 'postgresql@*-main' 2>/dev/null; then
      :
    fi
    sleep 1
  done
  if [[ "$ready" -ne 1 ]]; then
    msg_error "PostgreSQL did not become ready (socket /var/run/postgresql)"
    exit 1
  fi
  msg_ok "PostgreSQL running"
}

configure_postgres_auth() {
  # Allow password auth over local TCP so the app can use 127.0.0.1
  local hba conf
  hba="$(ls -1 /etc/postgresql/*/main/pg_hba.conf 2>/dev/null | head -n1 || true)"
  conf="$(ls -1 /etc/postgresql/*/main/postgresql.conf 2>/dev/null | head -n1 || true)"

  if [[ -n "$conf" ]]; then
    if grep -qE "^#?listen_addresses\s*=" "$conf"; then
      sed -i "s/^#\?listen_addresses\s*=.*/listen_addresses = 'localhost'/" "$conf"
    else
      echo "listen_addresses = 'localhost'" >>"$conf"
    fi
  fi

  if [[ -n "$hba" ]]; then
    # Remove previous WRU markers, then insert scram rules near the top (after comments)
    sed -i '/# WRU-BEGIN/,/# WRU-END/d' "$hba"
    local tmp
    tmp="$(mktemp)"
    {
      echo "# WRU-BEGIN"
      echo "local   ${PG_DB}   ${PG_USER}                   scram-sha-256"
      echo "host    ${PG_DB}   ${PG_USER}   127.0.0.1/32    scram-sha-256"
      echo "host    ${PG_DB}   ${PG_USER}   ::1/128         scram-sha-256"
      echo "# WRU-END"
      cat "$hba"
    } >"$tmp"
    mv "$tmp" "$hba"
    chown postgres:postgres "$hba" 2>/dev/null || true
  fi

  systemctl reload postgresql 2>/dev/null || service postgresql reload 2>/dev/null || \
    su -s /bin/bash postgres -c "psql -c \"SELECT pg_reload_conf()\"" >/dev/null 2>&1 || true
}

ensure_postgres_running
configure_postgres_auth

PG_PASS="$(load_existing_pg_password)"
if [[ -z "$PG_PASS" ]]; then
  PG_PASS="$(openssl rand -base64 24 | tr -dc 'A-Za-z0-9' | head -c 24)"
fi
PG_PASS_SQL="${PG_PASS//\'/\'\'}"

msg_info "Configuring PostgreSQL database"
su -s /bin/bash postgres -c "psql -v ON_ERROR_STOP=1" <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${PG_USER}') THEN
    CREATE ROLE ${PG_USER} LOGIN PASSWORD '${PG_PASS_SQL}';
  ELSE
    ALTER ROLE ${PG_USER} WITH LOGIN PASSWORD '${PG_PASS_SQL}';
  END IF;
END
\$\$;
SELECT 'CREATE DATABASE ${PG_DB} OWNER ${PG_USER} ENCODING ''UTF8'' TEMPLATE template0'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${PG_DB}')\gexec
GRANT ALL PRIVILEGES ON DATABASE ${PG_DB} TO ${PG_USER};
SQL
# Prefer UTF-8 client encoding on existing DBs (SQL_ASCII templates break Unicode seed)
su -s /bin/bash postgres -c "psql -d ${PG_DB} -v ON_ERROR_STOP=1" <<SQL
ALTER DATABASE ${PG_DB} SET client_encoding TO 'UTF8';
GRANT ALL ON SCHEMA public TO ${PG_USER};
ALTER SCHEMA public OWNER TO ${PG_USER};
SQL
msg_ok "Database ${PG_DB} ready"

PG_PASS_ENC="$(urlencode "$PG_PASS")"
# Prefer Unix socket (reliable in LXC); TCP 127.0.0.1 as fallback
PG_SOCKET_DIR="/var/run/postgresql"
if [[ -d "$PG_SOCKET_DIR" ]] && compgen -G "${PG_SOCKET_DIR}/.s.PGSQL.*" >/dev/null; then
  DATABASE_URL="postgresql+psycopg2://${PG_USER}:${PG_PASS_ENC}@/${PG_DB}?host=${PG_SOCKET_DIR}&client_encoding=utf8"
  PG_HOST="$PG_SOCKET_DIR"
else
  PG_HOST="${POSTGRES_HOST:-127.0.0.1}"
  DATABASE_URL="postgresql+psycopg2://${PG_USER}:${PG_PASS_ENC}@${PG_HOST}:${PG_PORT}/${PG_DB}?client_encoding=utf8"
fi

msg_info "Creating application user"
if ! id -u "$APP_USER" >/dev/null 2>&1; then
  useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
fi
msg_ok "Application user ready"

msg_info "Deploying ${APP}"
mkdir -p "$DATA_DIR/uploads" || true
TMP_APP="$(mktemp -d)"
NEW_APP="$TMP_APP/wru"
if ! git clone --depth 1 --branch "$APP_BRANCH" "$APP_GIT" "$NEW_APP" >/dev/null 2>&1; then
  rm -rf "$NEW_APP"
  msg_warn "Clone by ref name failed — retrying (commit SHA / tag)"
  if git clone --depth 50 "$APP_GIT" "$NEW_APP" >/dev/null 2>&1; then
    git -C "$NEW_APP" fetch --depth 50 origin "$APP_BRANCH" >/dev/null 2>&1 || true
    git -C "$NEW_APP" checkout "$APP_BRANCH" >/dev/null 2>&1 || true
  fi
fi
if [[ ! -f "$NEW_APP/app/main.py" ]]; then
  msg_error "Failed to clone ${APP_GIT} (${APP_BRANCH})"
  rm -rf "$TMP_APP"
  exit 1
fi
# Never build the venv under /tmp and then move it — that breaks pip/sqlalchemy
# (shebangs and pyvenv.cfg still point at the temp path).
rm -rf "${APP_DIR}.prev"
if [[ -d "$APP_DIR" ]]; then
  mv "$APP_DIR" "${APP_DIR}.prev"
fi
mv "$NEW_APP" "$APP_DIR"
rm -rf "$TMP_APP"
rm -rf "$APP_DIR/data"
msg_ok "Deployed ${APP} (${APP_BRANCH})"

restore_previous_app() {
  if [[ -d "${APP_DIR}.prev" ]]; then
    rm -rf "$APP_DIR"
    mv "${APP_DIR}.prev" "$APP_DIR"
    msg_warn "Restored previous ${APP_DIR}"
  fi
}

msg_info "Creating Python virtualenv"
if ! python3 -m venv "$APP_DIR/.venv"; then
  msg_error "python3 -m venv failed — installing python3-venv and retrying"
  $STD apt-get install -y python3-venv python3-full || true
  if ! python3 -m venv "$APP_DIR/.venv"; then
    restore_previous_app
    msg_error "python3 -m venv failed"
    exit 1
  fi
fi
VENV_PY="$APP_DIR/.venv/bin/python"
if ! "$VENV_PY" -m pip --version >/dev/null 2>&1; then
  echo "Bootstrapping pip into the venv…"
  "$VENV_PY" -m ensurepip --upgrade >/dev/null 2>&1 || true
fi
if ! "$VENV_PY" -m pip --version >/dev/null 2>&1; then
  tmp_pip="$(mktemp)"
  curl -fsSL --connect-timeout 15 --max-time 90 https://bootstrap.pypa.io/get-pip.py -o "$tmp_pip"
  "$VENV_PY" "$tmp_pip"
  rm -f "$tmp_pip"
fi
"$VENV_PY" -m pip install --upgrade pip || true
if ! "$VENV_PY" -m pip install -r "$APP_DIR/requirements.txt"; then
  msg_warn "Bulk pip install failed — retrying packages individually so WRU can still start"
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" || "$line" == \#* ]] && continue
    "$VENV_PY" -m pip install "$line" || msg_warn "Could not install $line"
  done < "$APP_DIR/requirements.txt"
fi
"$VENV_PY" -m pip install "pillow==11.1.0" || msg_warn "Pillow not installed — uploads still work, photos will not recompress"
if ! "$VENV_PY" -c "import sqlalchemy, fastapi, uvicorn"; then
  msg_warn "sqlalchemy still missing — leaving new code in place (do not restore a broken venv)"
  if [[ -f "$APP_DIR/scripts/wru-repair-venv.sh" ]]; then
    WRU_REPAIR_FORCE=1 bash "$APP_DIR/scripts/wru-repair-venv.sh" || true
  fi
fi
msg_ok "Installed Python packages"

msg_info "Writing environment"
# Read a quoted KEY=value from /etc/default/wru without sourcing the whole file
# (sourcing would clobber freshly computed DATABASE_URL for this install).
read_default_var() {
  local key="$1" file="/etc/default/wru" line val
  [[ -f "$file" ]] || return 0
  line="$(grep -E "^${key}=" "$file" | tail -n1 || true)"
  [[ -n "$line" ]] || return 0
  val="${line#*=}"
  eval "printf '%s' $val"
}
EXISTING_SECRET="$(read_default_var WRU_SECRET_KEY || true)"
EXISTING_ADMIN_USER="$(read_default_var WRU_ADMIN_USER || true)"
EXISTING_ADMIN_PASSWORD="$(read_default_var WRU_ADMIN_PASSWORD || true)"
EXISTING_ADMIN_NAME="$(read_default_var WRU_ADMIN_NAME || true)"
EXISTING_COOKIE_HTTPS="$(read_default_var WRU_COOKIE_HTTPS || true)"
if [[ -z "${WRU_SECRET_KEY:-}" ]]; then
  if [[ -n "$EXISTING_SECRET" ]]; then
    WRU_SECRET_KEY="$EXISTING_SECRET"
  else
    WRU_SECRET_KEY="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
)"
  fi
fi
# Optional bootstrap (only used when users table is empty)
if [[ -z "${WRU_ADMIN_USER:-}" ]]; then WRU_ADMIN_USER="${EXISTING_ADMIN_USER:-admin}"; fi
if [[ -z "${WRU_ADMIN_NAME:-}" ]]; then WRU_ADMIN_NAME="${EXISTING_ADMIN_NAME:-Administrator}"; fi
if [[ -z "${WRU_ADMIN_PASSWORD:-}" ]]; then WRU_ADMIN_PASSWORD="${EXISTING_ADMIN_PASSWORD:-}"; fi
if [[ -z "${WRU_COOKIE_HTTPS:-}" ]]; then WRU_COOKIE_HTTPS="${EXISTING_COOKIE_HTTPS:-}"; fi

# Quote every value — DATABASE_URL contains &client_encoding=… which breaks unquoted
# /etc/default files when sourced (KeyError: DATABASE_URL / truncated URL).
{
  echo "WRU_DATA_DIR=${DATA_DIR@Q}"
  echo "WRU_PORT=${APP_PORT@Q}"
  echo "POSTGRES_USER=${PG_USER@Q}"
  echo "POSTGRES_PASSWORD=${PG_PASS@Q}"
  echo "POSTGRES_HOST=${PG_HOST@Q}"
  echo "POSTGRES_PORT=${PG_PORT@Q}"
  echo "POSTGRES_DB=${PG_DB@Q}"
  echo "DATABASE_URL=${DATABASE_URL@Q}"
  echo "WRU_SECRET_KEY=${WRU_SECRET_KEY@Q}"
  echo "WRU_ADMIN_USER=${WRU_ADMIN_USER@Q}"
  echo "WRU_ADMIN_NAME=${WRU_ADMIN_NAME@Q}"
  if [[ -n "$WRU_ADMIN_PASSWORD" ]]; then
    echo "WRU_ADMIN_PASSWORD=${WRU_ADMIN_PASSWORD@Q}"
  fi
  if [[ -n "$WRU_COOKIE_HTTPS" ]]; then
    echo "WRU_COOKIE_HTTPS=${WRU_COOKIE_HTTPS@Q}"
  fi
} >/etc/default/wru
chmod 640 /etc/default/wru
chown root:"${APP_USER}" /etc/default/wru || true
msg_ok "Wrote /etc/default/wru"

msg_info "Setting permissions"
chown -R "${APP_USER}:${APP_USER}" "$APP_DIR" || true
chown -R "${APP_USER}:${APP_USER}" "$DATA_DIR" || true
chmod 755 "$APP_DIR" "$DATA_DIR" || true
mkdir -p "$DATA_DIR/uploads" "$DATA_DIR/uploads/archived" || true
chown -R "${APP_USER}:${APP_USER}" "$DATA_DIR" || true
msg_ok "Permissions set"

msg_info "Migrating and seeding database"
set -a
# shellcheck disable=SC1091
source /etc/default/wru
set +a
export DATABASE_URL="${DATABASE_URL:-}"
if [[ -z "$DATABASE_URL" ]]; then
  msg_warn "DATABASE_URL missing after writing /etc/default/wru — starting the app anyway"
fi
cd "$APP_DIR"
VENV_PY="${VENV_PY:-$APP_DIR/.venv/bin/python}"

# Prove DB login works before migrations (shows real errors)
"$VENV_PY" - <<'PY' || msg_warn "Database connection failed — starting the app anyway"
import os, sys
from sqlalchemy import create_engine, text
url = os.environ.get("DATABASE_URL")
if not url:
    print("DATABASE_URL is not set in the environment", file=sys.stderr)
    sys.exit(1)
try:
    eng = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5})
    with eng.connect() as conn:
        conn.execute(text("SELECT 1"))
except Exception as exc:
    print(f"Database connection failed: {exc}", file=sys.stderr)
    sys.exit(1)
print("Database connection OK")
PY

"$VENV_PY" -c "from app.migrate import run_migrations; run_migrations()" || msg_warn "Migration reported an error — starting the app anyway"
if ! "$VENV_PY" scripts/seed.py; then
  msg_warn "Sample seed skipped (existing data is left as-is)"
fi
if [[ -f "${DATA_DIR}/bootstrap_admin.txt" ]]; then
  msg_warn "First admin credentials: ${DATA_DIR}/bootstrap_admin.txt (change password after login)"
fi
msg_ok "Database ready"

msg_info "Creating Service"
cat <<EOF >/etc/systemd/system/${SERVICE_NAME}.service
[Unit]
Description=WRU TGS Tracker
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=/etc/default/wru
ExecStart=${APP_DIR}/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port \${WRU_PORT}
Restart=on-failure
RestartSec=5
TimeoutStartSec=25
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable -q --now "$SERVICE_NAME"
msg_ok "Created and started ${SERVICE_NAME}.service"

msg_info "Installing GitHub update helper"
UPDATE_SRC="${APP_DIR}/scripts/wru-update.sh"
ONLINE_SRC="${APP_DIR}/scripts/wru-online-update.sh"
if [[ -f "$UPDATE_SRC" ]]; then
  install -m 755 "$UPDATE_SRC" /usr/local/sbin/wru-update
  install -m 755 "$UPDATE_SRC" /usr/bin/wru-update
  ln -sfn /usr/local/sbin/wru-update /usr/local/sbin/WRU-update
  ln -sfn /usr/bin/wru-update /usr/bin/WRU-update
  if [[ -f "$ONLINE_SRC" ]]; then
    install -m 755 "$ONLINE_SRC" /usr/local/sbin/wru-online-update
    install -m 755 "$ONLINE_SRC" /usr/bin/wru-online-update
  fi
  if [[ -f "${APP_DIR}/scripts/wru-repair-venv.sh" ]]; then
    install -m 755 "${APP_DIR}/scripts/wru-repair-venv.sh" /usr/local/sbin/wru-repair-venv
    install -m 755 "${APP_DIR}/scripts/wru-repair-venv.sh" /usr/bin/wru-repair-venv
  fi
  # Minimal LXCs may lack /etc/sudoers.d until sudo is installed
  $STD apt-get install -y sudo >/dev/null 2>&1 || true
  mkdir -p /etc/sudoers.d
  if [[ -f /etc/sudoers ]] && ! grep -qE '^[@#]includedir[[:space:]]+/etc/sudoers\.d' /etc/sudoers; then
    printf '\n#includedir /etc/sudoers.d\n' >>/etc/sudoers
  fi
  cat >/etc/sudoers.d/wru-update <<'EOF'
# Allow WRU service user to pull/install updates from GitHub without a password
wru ALL=(root) NOPASSWD: /usr/local/sbin/wru-online-update
wru ALL=(root) NOPASSWD: /usr/bin/wru-online-update
wru ALL=(root) NOPASSWD: /usr/local/sbin/wru-update
wru ALL=(root) NOPASSWD: /usr/local/sbin/WRU-update
wru ALL=(root) NOPASSWD: /usr/bin/wru-update
wru ALL=(root) NOPASSWD: /usr/bin/WRU-update
wru ALL=(root) NOPASSWD: /usr/local/sbin/wru-repair-venv
wru ALL=(root) NOPASSWD: /usr/bin/wru-repair-venv
wru ALL=(root) NOPASSWD: /usr/bin/systemd-run
wru ALL=(root) NOPASSWD: /usr/bin/systemctl reset-failed wru-online-update*
wru ALL=(root) NOPASSWD: /bin/systemctl reset-failed wru-online-update*
EOF
  chmod 440 /etc/sudoers.d/wru-update
  if command -v visudo >/dev/null 2>&1 && ! visudo -cf /etc/sudoers.d/wru-update >/dev/null 2>&1; then
    msg_warn "sudoers file invalid — removed; in-app updates may need a manual fix"
    rm -f /etc/sudoers.d/wru-update
  else
    msg_ok "Installed sudo wru-update (also WRU-update) for user wru"
  fi
else
  msg_warn "scripts/wru-update.sh missing — skipped update helper"
fi

COMMIT="$(git -C "$APP_DIR" rev-parse --short HEAD 2>/dev/null || echo unknown)"
if [[ -f "$APP_DIR/VERSION" ]]; then
  APP_VER="$(tr -d '[:space:]' <"$APP_DIR/VERSION" | sed 's/^v//')"
else
  APP_VER="$(python3 - <<'PY'
import re, pathlib
text = pathlib.Path("/opt/wru/app/main.py").read_text()
m = re.search(r'version\s*=\s*"([^"]+)"', text)
print(m.group(1).lstrip("vV") if m else "unknown")
PY
)"
fi
cat >"/opt/${APP_SLUG}_version.txt" <<EOF
branch=${APP_BRANCH}
repo=${APP_GIT}
app_version=${APP_VER}
version_tag=v${APP_VER}
updated_at=$(date -Is)
commit=${COMMIT}
EOF
chmod 644 "/opt/${APP_SLUG}_version.txt"
# Ensure history file exists (updater snapshots into it on subsequent upgrades)
if [[ ! -f "/opt/${APP_SLUG}_version_history.json" ]]; then
  echo '{"versions":[]}' >"/opt/${APP_SLUG}_version_history.json"
  chmod 644 "/opt/${APP_SLUG}_version_history.json"
fi

# Helper MOTD tip
if [[ -d /etc/update-motd.d ]]; then
  cat <<EOF >/etc/update-motd.d/99-wru
#!/bin/sh
echo ""
echo "  WRU TGS Tracker   →  http://\$(hostname -I | awk '{print \$1}'):${APP_PORT}/login"
echo "  Service          →  systemctl status ${SERVICE_NAME}"
echo "  Update / rollback →  sudo wru-update   or  /admin/system"
echo "  First admin      →  ${DATA_DIR}/bootstrap_admin.txt (if present)"
echo "  Database         →  PostgreSQL (${PG_DB})"
echo "  Uploads          →  ${DATA_DIR}/uploads"
echo ""
EOF
  chmod +x /etc/update-motd.d/99-wru
fi

motd_ssh
customize
cleanup_lxc

IP_ADDR="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo -e "\n${INFO:-ℹ} ${APP} installed."
echo -e "Access URL: http://${IP_ADDR:-<container-ip>}:${APP_PORT}/login"
echo -e "Service:    systemctl status ${SERVICE_NAME}"
echo -e "Update:     sudo wru-update  (or open /admin/system)"
echo -e "Users:      Admin → Users  (bootstrap password in ${DATA_DIR}/bootstrap_admin.txt if created)"
echo -e "Database:   PostgreSQL db=${PG_DB} user=${PG_USER}"
echo -e "Uploads:    ${DATA_DIR}/uploads\n"
