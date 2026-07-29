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

APP="WRU"
APP_DIR="/opt/wru"
DATA_DIR="/opt/wru-data"
SERVICE_NAME="wru"
APP_PORT="${WRU_PORT:-8000}"
APP_GIT="${WRU_REPO:-https://github.com/McKrackenAU/WRU.git}"
APP_BRANCH="${WRU_BRANCH:-main}"
APP_USER="wru"

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

  STD="silent"
  silent() { "$@" >/dev/null 2>&1; }

  catch_errors() {
    set -Eeuo pipefail
    trap 'msg_error "Failed at line $LINENO"; exit 1' ERR
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

msg_info "Installing Dependencies"
$STD apt-get install -y \
  python3 \
  python3-venv \
  python3-pip \
  git \
  curl \
  ca-certificates
msg_ok "Installed Dependencies"

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
python3 -m venv "$APP_DIR/.venv"
# shellcheck disable=SC1091
source "$APP_DIR/.venv/bin/activate"
$STD pip install --upgrade pip
$STD pip install -r "$APP_DIR/requirements.txt"
deactivate
msg_ok "Installed Python packages"

msg_info "Writing environment"
cat <<EOF >/etc/default/wru
WRU_DATA_DIR=${DATA_DIR}
WRU_PORT=${APP_PORT}
DATABASE_URL=sqlite:///${DATA_DIR}/wru.db
EOF
chmod 644 /etc/default/wru
msg_ok "Wrote /etc/default/wru"

msg_info "Seeding database"
# shellcheck disable=SC1091
source "$APP_DIR/.venv/bin/activate"
export WRU_DATA_DIR="$DATA_DIR"
export DATABASE_URL="sqlite:///${DATA_DIR}/wru.db"
cd "$APP_DIR"
python3 scripts/seed.py
deactivate
msg_ok "Database ready"

msg_info "Setting permissions"
chown -R "${APP_USER}:${APP_USER}" "$APP_DIR" "$DATA_DIR"
chmod 755 "$APP_DIR" "$DATA_DIR"
msg_ok "Permissions set"

msg_info "Creating Service"
cat <<EOF >/etc/systemd/system/${SERVICE_NAME}.service
[Unit]
Description=WRU LCP-FMRP MoA Tracker
After=network.target
Wants=network-online.target

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

echo "${APP_BRANCH}" >"/opt/${APP}_version.txt"
chmod 644 "/opt/${APP}_version.txt"

# Helper MOTD tip
if [[ -d /etc/update-motd.d ]]; then
  cat <<EOF >/etc/update-motd.d/99-wru
#!/bin/sh
echo ""
echo "  WRU MoA Tracker  →  http://\$(hostname -I | awk '{print \$1}'):${APP_PORT}"
echo "  Service          →  systemctl status ${SERVICE_NAME}"
echo "  Data             →  ${DATA_DIR}"
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
echo -e "Data dir:   ${DATA_DIR}\n"
