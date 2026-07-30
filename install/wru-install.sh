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
  python3-full \
  git \
  curl \
  ca-certificates \
  postgresql \
  postgresql-contrib \
  libpq5
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
SELECT 'CREATE DATABASE ${PG_DB} OWNER ${PG_USER}'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${PG_DB}')\gexec
GRANT ALL PRIVILEGES ON DATABASE ${PG_DB} TO ${PG_USER};
SQL
# Schema privileges for Postgres 15+
su -s /bin/bash postgres -c "psql -d ${PG_DB} -v ON_ERROR_STOP=1" <<SQL
GRANT ALL ON SCHEMA public TO ${PG_USER};
ALTER SCHEMA public OWNER TO ${PG_USER};
SQL
msg_ok "Database ${PG_DB} ready"

PG_PASS_ENC="$(urlencode "$PG_PASS")"
# Prefer Unix socket (reliable in LXC); TCP 127.0.0.1 as fallback
PG_SOCKET_DIR="/var/run/postgresql"
if [[ -d "$PG_SOCKET_DIR" ]] && compgen -G "${PG_SOCKET_DIR}/.s.PGSQL.*" >/dev/null; then
  DATABASE_URL="postgresql+psycopg2://${PG_USER}:${PG_PASS_ENC}@/${PG_DB}?host=${PG_SOCKET_DIR}"
  PG_HOST="$PG_SOCKET_DIR"
else
  PG_HOST="${POSTGRES_HOST:-127.0.0.1}"
  DATABASE_URL="postgresql+psycopg2://${PG_USER}:${PG_PASS_ENC}@${PG_HOST}:${PG_PORT}/${PG_DB}"
fi

msg_info "Creating application user"
if ! id -u "$APP_USER" >/dev/null 2>&1; then
  useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
fi
msg_ok "Application user ready"

msg_info "Deploying ${APP}"
mkdir -p "$DATA_DIR/uploads"
TMP_APP="$(mktemp -d)"
if ! git clone --depth 1 --branch "$APP_BRANCH" "$APP_GIT" "$TMP_APP/wru" >/dev/null 2>&1; then
  msg_error "Failed to clone ${APP_GIT} (${APP_BRANCH})"
  exit 1
fi
rm -rf "$APP_DIR"
mv "$TMP_APP/wru" "$APP_DIR"
rm -rf "$TMP_APP"
rm -rf "$APP_DIR/data"
msg_ok "Deployed ${APP} (${APP_BRANCH})"

msg_info "Creating Python virtualenv"
if ! python3 -m venv "$APP_DIR/.venv"; then
  msg_error "python3 -m venv failed — installing python3-venv and retrying"
  $STD apt-get install -y python3-venv python3-full
  python3 -m venv "$APP_DIR/.venv"
fi
# shellcheck disable=SC1091
source "$APP_DIR/.venv/bin/activate"
if ! command -v pip >/dev/null 2>&1; then
  msg_error "venv pip missing after create"
  exit 1
fi
pip install --upgrade pip
pip install -r "$APP_DIR/requirements.txt"
deactivate
msg_ok "Installed Python packages"

msg_info "Writing environment"
cat <<EOF >/etc/default/wru
WRU_DATA_DIR=${DATA_DIR}
WRU_PORT=${APP_PORT}
POSTGRES_USER=${PG_USER}
POSTGRES_PASSWORD=${PG_PASS}
POSTGRES_HOST=${PG_HOST}
POSTGRES_PORT=${PG_PORT}
POSTGRES_DB=${PG_DB}
DATABASE_URL=${DATABASE_URL}
EOF
chmod 640 /etc/default/wru
chown root:"${APP_USER}" /etc/default/wru
msg_ok "Wrote /etc/default/wru"

msg_info "Setting permissions"
chown -R "${APP_USER}:${APP_USER}" "$APP_DIR" "$DATA_DIR"
chmod 755 "$APP_DIR" "$DATA_DIR"
msg_ok "Permissions set"

msg_info "Migrating and seeding database"
# shellcheck disable=SC1091
source "$APP_DIR/.venv/bin/activate"
set -a
# shellcheck disable=SC1091
source /etc/default/wru
set +a
cd "$APP_DIR"

# Prove DB login works before migrations (shows real errors)
python3 - <<'PY'
import os, sys
from sqlalchemy import create_engine, text
url = os.environ["DATABASE_URL"]
try:
    eng = create_engine(url, pool_pre_ping=True)
    with eng.connect() as conn:
        conn.execute(text("SELECT 1"))
except Exception as exc:
    print(f"Database connection failed: {exc}", file=sys.stderr)
    sys.exit(1)
print("Database connection OK")
PY

python3 -c "from app.migrate import run_migrations; run_migrations()"
if ! python3 scripts/seed.py; then
  msg_warn "Sample seed failed (schema is migrated); continuing"
fi
deactivate
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
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable -q --now "$SERVICE_NAME"
msg_ok "Created and started ${SERVICE_NAME}.service"

msg_info "Installing GitHub update helper"
UPDATE_SRC="${APP_DIR}/scripts/wru-update.sh"
if [[ -f "$UPDATE_SRC" ]]; then
  install -m 755 "$UPDATE_SRC" /usr/local/sbin/wru-update
  cat >/etc/sudoers.d/wru-update <<'EOF'
# Allow WRU service user to pull/install updates from GitHub without a password
wru ALL=(root) NOPASSWD: /usr/local/sbin/wru-update
wru ALL=(root) NOPASSWD: /usr/bin/systemd-run
wru ALL=(root) NOPASSWD: /bin/systemctl reset-failed wru-online-update.service
EOF
  chmod 440 /etc/sudoers.d/wru-update
  msg_ok "Installed /usr/local/sbin/wru-update (sudo for user wru)"
else
  msg_warn "scripts/wru-update.sh missing — skipped update helper"
fi

COMMIT="$(git -C "$APP_DIR" rev-parse --short HEAD 2>/dev/null || echo unknown)"
APP_VER="$(python3 - <<'PY'
import re, pathlib
text = pathlib.Path("/opt/wru/app/main.py").read_text()
m = re.search(r'version\s*=\s*"([^"]+)"', text)
print(m.group(1) if m else "unknown")
PY
)"
cat >"/opt/${APP_SLUG}_version.txt" <<EOF
branch=${APP_BRANCH}
repo=${APP_GIT}
app_version=${APP_VER}
updated_at=$(date -Is)
commit=${COMMIT}
EOF
chmod 644 "/opt/${APP_SLUG}_version.txt"

# Helper MOTD tip
if [[ -d /etc/update-motd.d ]]; then
  cat <<EOF >/etc/update-motd.d/99-wru
#!/bin/sh
echo ""
echo "  WRU TGS Tracker   →  http://\$(hostname -I | awk '{print \$1}'):${APP_PORT}"
echo "  Service          →  systemctl status ${SERVICE_NAME}"
echo "  Update           →  sudo wru-update   or  /system in the UI"
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
echo -e "Access URL: http://${IP_ADDR:-<container-ip>}:${APP_PORT}"
echo -e "Service:    systemctl status ${SERVICE_NAME}"
echo -e "Update:     sudo wru-update  (or open /system)"
echo -e "Database:   PostgreSQL db=${PG_DB} user=${PG_USER}"
echo -e "Uploads:    ${DATA_DIR}/uploads\n"
