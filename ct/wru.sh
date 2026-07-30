#!/usr/bin/env bash
# Copyright (c) 2026 McKrackenAU / WRU
# Author: William McClure
# License: Apache-2.0 | https://github.com/McKrackenAU/WRU/blob/main/LICENSE
# Source: https://github.com/McKrackenAU/WRU
#
# Proxmox VE Helper Scripts–style entrypoint.
# Run on the Proxmox host:
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/McKrackenAU/WRU/main/ct/wru.sh)"
#
# Or from a local checkout:
#   bash ct/wru.sh
#
# Optional env overrides:
#   WRU_BRANCH=main WRU_PORT=8000 CTID=230 HN=wru STORAGE=local-lvm bash ct/wru.sh

set -eEuo pipefail

APP="WRU TGS Tracker"
APP_PORT="${WRU_PORT:-8000}"
APP_GIT="${WRU_REPO:-https://github.com/McKrackenAU/WRU.git}"
APP_BRANCH="${WRU_BRANCH:-main}"
RAW_BASE="${WRU_RAW_BASE:-https://raw.githubusercontent.com/McKrackenAU/WRU/${APP_BRANCH}}"

var_cpu="${var_cpu:-1}"
var_ram="${var_ram:-2048}"
var_disk="${var_disk:-8}"
var_os="${var_os:-debian}"
var_version="${var_version:-12}"
var_unprivileged="${var_unprivileged:-1}"
HN="${HN:-wru}"
PASSWORD="${PASSWORD:-}"
BRIDGE="${BRIDGE:-vmbr0}"
STORAGE="${STORAGE:-}"
CTID="${CTID:-}"

YW=$'\033[33m'
BL=$'\033[36m'
RD=$'\033[01;31m'
BGN=$'\033[4;92m'
GN=$'\033[1;92m'
DGN=$'\033[32m'
CL=$'\033[m'
BFR=$'\r\033[K'
HOLD="-"
CM="${GN}✓${CL}"
CROSS="${RD}✗${CL}"
INFO="${BL}ℹ${CL}"

msg_info() { echo -ne " ${HOLD} ${YW}${1}...${CL}"; }
msg_ok() { echo -e "${BFR} ${CM} ${GN}${1}${CL}"; }
msg_error() { echo -e "${BFR} ${CROSS} ${RD}${1}${CL}"; }

header_info() {
  clear 2>/dev/null || true
  cat <<"EOF"
    _       __________  __  __
   | |     / / __/ / / / / / /
   | | /| / / /_/ / /_/ / / /
   | |/ |/ / __/ / _, _/ /_/
   |__/|__/_/ /_/_/ |_|\____/

  WRU TGS Tracker
  Proxmox Helper Script Installer
EOF
  echo -e "\n${INFO} Repo: ${APP_GIT} (${APP_BRANCH})\n"
}

trap 'msg_error "Script failed near line $LINENO"; exit 1' ERR

is_proxmox_host() {
  command -v pveversion >/dev/null 2>&1 && command -v pct >/dev/null 2>&1
}

resolve_script_dir() {
  local src="${BASH_SOURCE[0]:-}"
  if [[ -n "$src" && -f "$src" ]]; then
    cd "$(dirname "$src")" && pwd
  else
    echo ""
  fi
}

SCRIPT_DIR="$(resolve_script_dir)"
REPO_ROOT=""
if [[ -n "$SCRIPT_DIR" && -f "${SCRIPT_DIR}/../install/wru-install.sh" ]]; then
  REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
fi

fetch_install_script_to() {
  local dest="$1"
  if [[ -n "$REPO_ROOT" && -f "${REPO_ROOT}/install/wru-install.sh" ]]; then
    cp "${REPO_ROOT}/install/wru-install.sh" "$dest"
  else
    curl -fsSL "${RAW_BASE}/install/wru-install.sh" -o "$dest"
  fi
  chmod +x "$dest"
}

next_ctid() {
  local id=100
  while pct status "$id" &>/dev/null; do
    id=$((id + 1))
  done
  echo "$id"
}

default_storage() {
  if [[ -n "$STORAGE" ]]; then
    echo "$STORAGE"
    return
  fi
  pvesm status -content rootdir 2>/dev/null | awk 'NR>1 {print $1; exit}'
}

ensure_root() {
  if [[ "$(id -u)" -ne 0 ]]; then
    msg_error "Must run as root on the Proxmox host"
    exit 1
  fi
}

ensure_template() {
  local storage_tmpl="local"
  msg_info "Refreshing appliance templates"
  pveam update >/dev/null 2>&1 || true
  msg_ok "Template catalog refreshed"

  local available
  available="$(pveam available --section system 2>/dev/null | awk -v ver="$var_version" '
    $0 ~ ("debian-" ver "-standard") && /amd64/ {print $2; exit}
  ')"
  if [[ -z "$available" ]]; then
    available="$(pveam available --section system 2>/dev/null | awk '
      /debian-12-standard/ && /amd64/ {print $2; exit}
    ')"
  fi
  if [[ -z "$available" ]]; then
    msg_error "Could not find a Debian standard amd64 template via pveam"
    exit 1
  fi

  if ! pveam list "$storage_tmpl" 2>/dev/null | grep -Fq "$available"; then
    msg_info "Downloading ${available}"
    pveam download "$storage_tmpl" "$available" >/dev/null
    msg_ok "Downloaded template"
  else
    msg_ok "Template already present"
  fi

  TEMPLATE_PATH="${storage_tmpl}:vztmpl/${available}"
}

update_inside_container() {
  header_info
  if [[ ! -d /opt/wru ]]; then
    msg_error "No ${APP} installation found in this container"
    exit 1
  fi

  msg_info "Stopping service"
  systemctl stop wru || true
  msg_ok "Stopped service"

  local tmp
  tmp="$(mktemp)"
  fetch_install_script_to "$tmp"
  export WRU_REPO="$APP_GIT" WRU_BRANCH="$APP_BRANCH" WRU_PORT="$APP_PORT"
  bash "$tmp"
  rm -f "$tmp"

  msg_ok "Updated ${APP} successfully"
  local ip
  ip="$(hostname -I | awk '{print $1}')"
  echo -e "${INFO} Access URL: ${BGN}http://${ip}:${APP_PORT}${CL}\n"
  exit 0
}

create_lxc() {
  ensure_root
  header_info

  CTID="${CTID:-$(next_ctid)}"
  STORAGE="$(default_storage)"
  if [[ -z "$STORAGE" ]]; then
    msg_error "No storage with rootdir content found. Set STORAGE=..."
    exit 1
  fi
  if [[ -z "$PASSWORD" ]]; then
    PASSWORD="$(openssl rand -base64 24 | tr -dc 'A-Za-z0-9' | head -c 16)"
  fi

  echo -e "${INFO} Defaults"
  echo -e "  CTID:      ${BL}${CTID}${CL}"
  echo -e "  Hostname:  ${BL}${HN}${CL}"
  echo -e "  OS:        ${BL}${var_os} ${var_version}${CL}"
  echo -e "  CPU/RAM:   ${BL}${var_cpu} / ${var_ram}MiB${CL}"
  echo -e "  Disk:      ${BL}${var_disk}G${CL}"
  echo -e "  Storage:   ${BL}${STORAGE}${CL}"
  echo -e "  Bridge:    ${BL}${BRIDGE}${CL}"
  echo -e "  Root pass: ${BL}${PASSWORD}${CL}"
  echo

  if [[ -t 0 ]]; then
    read -r -p "Proceed with these settings? [Y/n] " ans
    ans="${ans:-Y}"
    if [[ ! "$ans" =~ ^[Yy]$ ]]; then
      echo "Aborted."
      exit 0
    fi
  fi

  ensure_template

  msg_info "Creating LXC ${CTID}"
  pct create "$CTID" "$TEMPLATE_PATH" \
    --hostname "$HN" \
    --cores "$var_cpu" \
    --memory "$var_ram" \
    --rootfs "${STORAGE}:${var_disk}" \
    --net0 "name=eth0,bridge=${BRIDGE},ip=dhcp" \
    --unprivileged "$var_unprivileged" \
    --features nesting=1 \
    --onboot 1 \
    --password "$PASSWORD" \
    --start 1 >/dev/null
  msg_ok "Created LXC ${CTID}"

  msg_info "Waiting for network"
  local ready=0
  for _ in $(seq 1 60); do
    if pct exec "$CTID" -- bash -c 'ping -c1 -W1 1.1.1.1 >/dev/null 2>&1 || ping -c1 -W1 8.8.8.8 >/dev/null 2>&1'; then
      ready=1
      break
    fi
    sleep 2
  done
  if [[ "$ready" -ne 1 ]]; then
    msg_error "Container network did not come up in time"
    exit 1
  fi
  msg_ok "Network ready"

  msg_info "Installing ${APP} inside CT ${CTID}"
  local host_tmp ct_tmp
  host_tmp="$(mktemp)"
  ct_tmp="/tmp/wru-install.sh"
  fetch_install_script_to "$host_tmp"
  pct push "$CTID" "$host_tmp" "$ct_tmp"
  pct exec "$CTID" -- chmod +x "$ct_tmp"
  pct exec "$CTID" -- env \
    WRU_REPO="$APP_GIT" \
    WRU_BRANCH="$APP_BRANCH" \
    WRU_PORT="$APP_PORT" \
    bash "$ct_tmp"
  rm -f "$host_tmp"
  msg_ok "Installed ${APP}"

  local ip
  ip="$(pct exec "$CTID" -- hostname -I | awk '{print $1}')"
  pct set "$CTID" -description $'WRU TGS Tracker\nURL: http://'"${ip}"':'"${APP_PORT}"$'\nRepo: '"${APP_GIT}"$'\nBranch: '"${APP_BRANCH}" >/dev/null || true

  echo
  msg_ok "Completed successfully!"
  echo -e " ${HOLD} ${YW}Creating:${CL} ${GN}${APP} LXC is ready${CL}"
  echo -e "${INFO}${YW} CTID:${CL} ${BL}${CTID}${CL}"
  echo -e "${INFO}${YW} Root password:${CL} ${BL}${PASSWORD}${CL}"
  echo -e " ${HOLD} ${DGN}Access URL:${CL} ${BGN}http://${ip}:${APP_PORT}${CL}\n"
}

install_bare_metal() {
  header_info
  echo -e "${INFO} Proxmox host tools not detected — running direct install path.\n"
  local tmp
  tmp="$(mktemp)"
  fetch_install_script_to "$tmp"
  export WRU_REPO="$APP_GIT" WRU_BRANCH="$APP_BRANCH" WRU_PORT="$APP_PORT"
  bash "$tmp"
  rm -f "$tmp"
}

main() {
  if [[ -d /opt/wru ]] && ! is_proxmox_host; then
    update_inside_container
  elif is_proxmox_host; then
    create_lxc
  else
    install_bare_metal
  fi
}

main "$@"
