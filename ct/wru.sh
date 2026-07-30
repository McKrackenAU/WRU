#!/usr/bin/env bash
# Copyright (c) 2026 McKrackenAU / WRU
# Author: William McClure
# License: Apache-2.0 | https://github.com/McKrackenAU/WRU/blob/main/LICENSE
# Source: https://github.com/McKrackenAU/WRU
#
# Proxmox VE Helper Scripts–style entrypoint with whiptail GUI.
# Run on the Proxmox host:
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/McKrackenAU/WRU/main/ct/wru.sh)"
#
# Or from a local checkout:
#   bash ct/wru.sh
#
# Optional env overrides (used as GUI defaults / noninteractive install):
#   WRU_BRANCH=main WRU_PORT=8000 CTID=230 HN=wru STORAGE=local-lvm \
#   NET=static IP_CIDR=192.168.1.50/24 GW=192.168.1.1 bash ct/wru.sh
#   NONINTERACTIVE=1  — skip whiptail; use env/defaults only

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
NET="${NET:-dhcp}"
IP_CIDR="${IP_CIDR:-}"
GW="${GW:-}"
NONINTERACTIVE="${NONINTERACTIVE:-0}"

YW=$'\033[33m'
BL=$'\033[36m'
RD=$'\033[01;31m'
BGN=$'\033[4;92m'
GN=$'\033[1;92m'
DGN=$'\033[32m'
CL=$'\033[m'
BOLD=$'\033[1m'
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
  Proxmox Helper Script Installer (whiptail GUI)
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

need_whiptail() {
  if command -v whiptail >/dev/null 2>&1; then
    return 0
  fi
  msg_info "Installing whiptail"
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq whiptail >/dev/null
  msg_ok "whiptail installed"
}

validate_static_net() {
  if [[ -z "$IP_CIDR" || "$IP_CIDR" != */* ]]; then
    msg_error "Static IP must be CIDR form, e.g. 192.168.1.50/24"
    exit 1
  fi
  if [[ -z "$GW" ]]; then
    msg_error "Gateway (GW) is required for static networking"
    exit 1
  fi
}

net0_arg() {
  if [[ "$NET" == "static" ]]; then
    validate_static_net
    echo "name=eth0,bridge=${BRIDGE},ip=${IP_CIDR},gw=${GW}"
  else
    echo "name=eth0,bridge=${BRIDGE},ip=dhcp"
  fi
}

pick_storage_gui() {
  local list=()
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    list+=("$line" "")
  done < <(pvesm status -content rootdir 2>/dev/null | awk 'NR>1 {print $1}')
  if [[ ${#list[@]} -eq 0 ]]; then
    while IFS= read -r line; do
      [[ -z "$line" ]] && continue
      list+=("$line" "")
    done < <(pvesm status 2>/dev/null | awk 'NR>1 {print $1}')
  fi
  if [[ ${#list[@]} -eq 0 ]]; then
    msg_error "No Proxmox storage found. Set STORAGE=..."
    exit 1
  fi
  local default_idx=1
  local i=1
  local name
  for ((i = 0; i < ${#list[@]}; i += 2)); do
    name="${list[$i]}"
    if [[ -n "$STORAGE" && "$name" == "$STORAGE" ]]; then
      default_idx=$((i / 2 + 1))
      break
    fi
  done
  STORAGE=$(whiptail --backtitle "$APP" --title "Storage" \
    --default-item "${list[$(( (default_idx - 1) * 2 ))]}" \
    --menu "Select storage for the CT root disk:" 18 60 10 \
    "${list[@]}" 3>&1 1>&2 2>&3) || exit 1
}

gui_settings() {
  need_whiptail

  if ! whiptail --backtitle "$APP" --title "$APP LXC" \
    --yesno "Create a new unprivileged Debian LXC and install ${APP}?\n\nCustomize CTID, resources, bridge, IP (DHCP or static), and app port." 13 72; then
    echo "Cancelled."
    exit 0
  fi

  CTID=$(whiptail --backtitle "$APP" --title "Container ID" \
    --inputbox "LXC Container ID:" 8 50 "${CTID:-$(next_ctid)}" 3>&1 1>&2 2>&3) || exit 1
  HN=$(whiptail --backtitle "$APP" --title "Hostname" \
    --inputbox "Hostname:" 8 50 "$HN" 3>&1 1>&2 2>&3) || exit 1
  var_cpu=$(whiptail --backtitle "$APP" --title "CPU" \
    --inputbox "CPU cores:" 8 50 "$var_cpu" 3>&1 1>&2 2>&3) || exit 1
  var_ram=$(whiptail --backtitle "$APP" --title "RAM" \
    --inputbox "RAM (MiB):" 8 50 "$var_ram" 3>&1 1>&2 2>&3) || exit 1
  var_disk=$(whiptail --backtitle "$APP" --title "Disk" \
    --inputbox "Root disk size (GiB):" 8 50 "$var_disk" 3>&1 1>&2 2>&3) || exit 1

  pick_storage_gui

  BRIDGE=$(whiptail --backtitle "$APP" --title "Bridge" \
    --inputbox "Network bridge:" 8 50 "$BRIDGE" 3>&1 1>&2 2>&3) || exit 1

  NET=$(whiptail --backtitle "$APP" --title "IP configuration" \
    --default-item "$NET" \
    --menu "Network mode:" 14 60 4 \
    "dhcp" "DHCP (automatic)" \
    "static" "Static IPv4 (CIDR + gateway)" 3>&1 1>&2 2>&3) || exit 1

  if [[ "$NET" == "static" ]]; then
    IP_CIDR=$(whiptail --backtitle "$APP" --title "Static IP" \
      --inputbox "IPv4 CIDR (e.g. 192.168.1.50/24):" 8 60 "${IP_CIDR}" 3>&1 1>&2 2>&3) || exit 1
    GW=$(whiptail --backtitle "$APP" --title "Gateway" \
      --inputbox "Gateway IP:" 8 50 "${GW}" 3>&1 1>&2 2>&3) || exit 1
    validate_static_net
  else
    IP_CIDR=""
    GW=""
  fi

  APP_PORT=$(whiptail --backtitle "$APP" --title "App port" \
    --inputbox "WRU HTTP listen port:" 8 50 "$APP_PORT" 3>&1 1>&2 2>&3) || exit 1

  local src
  src=$(whiptail --backtitle "$APP" --title "Git source" \
    --menu "Where should the CT clone WRU from?" 15 72 4 \
    "github" "GitHub — ${APP_GIT}" \
    "custom" "Enter a custom git URL" 3>&1 1>&2 2>&3) || exit 1

  if [[ "$src" == "custom" ]]; then
    APP_GIT=$(whiptail --backtitle "$APP" --title "Custom git URL" \
      --inputbox "Git clone URL:" 8 72 "$APP_GIT" 3>&1 1>&2 2>&3) || exit 1
    APP_BRANCH=$(whiptail --backtitle "$APP" --title "Git branch" \
      --inputbox "Branch:" 8 50 "$APP_BRANCH" 3>&1 1>&2 2>&3) || exit 1
  fi

  if [[ -z "$PASSWORD" ]]; then
    PASSWORD="$(openssl rand -base64 24 | tr -dc 'A-Za-z0-9' | head -c 16)"
  fi
  PASSWORD=$(whiptail --backtitle "$APP" --title "Root password" \
    --inputbox "LXC root password (leave as-is or change):" 9 60 "$PASSWORD" 3>&1 1>&2 2>&3) || exit 1

  local net_summary
  if [[ "$NET" == "static" ]]; then
    net_summary="static ${IP_CIDR} gw ${GW}"
  else
    net_summary="dhcp"
  fi

  local summary
  summary=$(
    cat <<EOF
CTID:       $CTID
Hostname:   $HN
CPU / RAM:  ${var_cpu} / ${var_ram} MiB
Disk:       ${var_disk}G on $STORAGE
Bridge:     $BRIDGE
Network:    $net_summary
App port:   $APP_PORT
Git:        $APP_GIT ($APP_BRANCH)
Root pass:  $PASSWORD
EOF
  )
  whiptail --backtitle "$APP" --title "Confirm" --yesno "Create container with these settings?\n\n$summary" 22 72 || exit 0
}

noninteractive_settings() {
  CTID="${CTID:-$(next_ctid)}"
  STORAGE="$(default_storage)"
  if [[ -z "$STORAGE" ]]; then
    msg_error "No storage with rootdir content found. Set STORAGE=..."
    exit 1
  fi
  if [[ -z "$PASSWORD" ]]; then
    PASSWORD="$(openssl rand -base64 24 | tr -dc 'A-Za-z0-9' | head -c 16)"
  fi
  if [[ "$NET" == "static" ]]; then
    validate_static_net
  fi

  echo -e "${INFO} Noninteractive defaults"
  echo -e "  CTID:      ${BL}${CTID}${CL}"
  echo -e "  Hostname:  ${BL}${HN}${CL}"
  echo -e "  OS:        ${BL}${var_os} ${var_version}${CL}"
  echo -e "  CPU/RAM:   ${BL}${var_cpu} / ${var_ram}MiB${CL}"
  echo -e "  Disk:      ${BL}${var_disk}G${CL}"
  echo -e "  Storage:   ${BL}${STORAGE}${CL}"
  echo -e "  Bridge:    ${BL}${BRIDGE}${CL}"
  if [[ "$NET" == "static" ]]; then
    echo -e "  Network:   ${BL}static ${IP_CIDR} gw ${GW}${CL}"
  else
    echo -e "  Network:   ${BL}dhcp${CL}"
  fi
  echo -e "  App port:  ${BL}${APP_PORT}${CL}"
  echo -e "  Root pass: ${BL}${PASSWORD}${CL}"
  echo
}

ensure_template() {
  local storage_tmpl="local"
  if pvesm status -content vztmpl 2>/dev/null | awk 'NR>1 {print $1}' | grep -qx local; then
    storage_tmpl="local"
  else
    storage_tmpl="$(pvesm status -content vztmpl 2>/dev/null | awk 'NR>1 {print $1; exit}')"
    storage_tmpl="${storage_tmpl:-local}"
  fi

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

  if [[ "$NONINTERACTIVE" == "1" ]] || [[ ! -t 0 ]]; then
    noninteractive_settings
  else
    gui_settings
  fi

  if pct status "$CTID" &>/dev/null; then
    msg_error "CT ${CTID} already exists"
    exit 1
  fi

  ensure_template

  local net_arg
  net_arg="$(net0_arg)"

  msg_info "Creating LXC ${CTID}"
  pct create "$CTID" "$TEMPLATE_PATH" \
    --hostname "$HN" \
    --cores "$var_cpu" \
    --memory "$var_ram" \
    --rootfs "${STORAGE}:${var_disk}" \
    --net0 "$net_arg" \
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
    msg_error "Container network did not come up in time (check bridge / DHCP / static IP + gateway)"
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
  if [[ "$NET" == "static" ]]; then
    ip="${IP_CIDR%%/*}"
  else
    ip="$(pct exec "$CTID" -- hostname -I | awk '{print $1}')"
  fi
  pct set "$CTID" -description $'WRU TGS Tracker\nURL: http://'"${ip}"':'"${APP_PORT}"$'\nRepo: '"${APP_GIT}"$'\nBranch: '"${APP_BRANCH}" >/dev/null || true

  echo
  msg_ok "Completed successfully!"
  echo -e " ${HOLD} ${YW}Creating:${CL} ${GN}${APP} LXC is ready${CL}"
  echo -e "${INFO}${YW} CTID:${CL} ${BL}${CTID}${CL}"
  echo -e "${INFO}${YW} Root password:${CL} ${BL}${PASSWORD}${CL}"
  if [[ "$NET" == "static" ]]; then
    echo -e "${INFO}${YW} Network:${CL} ${BL}${IP_CIDR} gw ${GW}${CL}"
  else
    echo -e "${INFO}${YW} Network:${CL} ${BL}dhcp${CL}"
  fi
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
