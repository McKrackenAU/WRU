#!/usr/bin/env bash
# Copyright (c) 2026 McKrackenAU / WRU
# Author: William McClure
# License: Apache-2.0 | https://github.com/McKrackenAU/WRU/blob/main/LICENSE
# Source: https://github.com/McKrackenAU/WRU
#
# Proxmox VE Helper Scripts–style entrypoint (Default / Advanced whiptail GUI).
# Run on the Proxmox host:
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/McKrackenAU/WRU/main/ct/wru.sh)"
#
# Or from a local checkout:
#   bash ct/wru.sh
#
# Matches the community-scripts install UX:
#   1) Default Install  — app defaults + storage picker
#   2) Advanced Install — full step wizard (IP, bridge, VLAN, DNS, features, …)
#   3) Update existing CT from GitHub — pull latest into an installed WRU LXC
#
# Env overrides (defaults / noninteractive):
#   mode=advanced|default|update  CTID=230 HN=wru var_cpu=2 var_ram=4096 var_disk=16
#   var_brg=vmbr0 var_net=192.168.1.50/24 var_gateway=192.168.1.1
#   WRU_PORT=8000 WRU_REPO=… WRU_BRANCH=main NONINTERACTIVE=1

set -eEuo pipefail

APP="WRU TGS Tracker"
NSAPP="wru"
APP_PORT="${WRU_PORT:-8000}"
APP_GIT="${WRU_REPO:-https://github.com/McKrackenAU/WRU.git}"
APP_BRANCH="${WRU_BRANCH:-main}"
RAW_BASE="${WRU_RAW_BASE:-https://raw.githubusercontent.com/McKrackenAU/WRU/${APP_BRANCH}}"

# App defaults (community-scripts style var_*)
var_tags="${var_tags:-productivity;tracker}"
var_cpu="${var_cpu:-1}"
var_ram="${var_ram:-2048}"
var_disk="${var_disk:-8}"
var_os="${var_os:-debian}"
var_version="${var_version:-12}"
var_unprivileged="${var_unprivileged:-1}"
var_brg="${var_brg:-${BRIDGE:-vmbr0}}"
var_net="${var_net:-${NET:-dhcp}}"
var_gateway="${var_gateway:-${GW:-}}"
var_ipv6_method="${var_ipv6_method:-auto}"
var_mtu="${var_mtu:-}"
var_searchdomain="${var_searchdomain:-}"
var_ns="${var_ns:-}"
var_mac="${var_mac:-}"
var_vlan="${var_vlan:-}"
var_ssh="${var_ssh:-no}"
var_fuse="${var_fuse:-no}"
var_tun="${var_tun:-no}"
var_nesting="${var_nesting:-1}"
var_keyctl="${var_keyctl:-0}"
var_protection="${var_protection:-no}"
var_timezone="${var_timezone:-}"
var_verbose="${var_verbose:-no}"
var_hostname="${var_hostname:-${HN:-wru}}"
var_ctid="${var_ctid:-${CTID:-}}"
var_pw="${var_pw:-${PASSWORD:-}}"
var_template_storage="${var_template_storage:-}"
var_container_storage="${var_container_storage:-${STORAGE:-}}"

NONINTERACTIVE="${NONINTERACTIVE:-0}"
METHOD="default"

# Runtime settings filled by Default / Advanced
CT_TYPE=""
CT_ID=""
HN=""
DISK_SIZE=""
CORE_COUNT=""
RAM_SIZE=""
BRG=""
NET=""
GATE=""
IPV6_METHOD=""
IPV6_ADDR=""
IPV6_GATE=""
MTU=""
SD=""
NS=""
MAC=""
VLAN=""
TAGS=""
SSH="no"
ENABLE_FUSE="no"
ENABLE_TUN="no"
ENABLE_NESTING="1"
ENABLE_KEYCTL="0"
PROTECT_CT="no"
CT_TIMEZONE=""
VERBOSE="no"
PW=""
PW_DISPLAY="Automatic Login"
TEMPLATE_STORAGE=""
CONTAINER_STORAGE=""
TEMPLATE_PATH=""

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
DEFAULT="${BL}"
ADVANCED="${RD}"
CREATING="${HOLD} ${YW}Creating:${CL}"

msg_info() { echo -ne " ${HOLD} ${YW}${1}...${CL}"; }
msg_ok() { echo -e "${BFR} ${CM} ${GN}${1}${CL}"; }
msg_error() { echo -e "${BFR} ${CROSS} ${RD}${1}${CL}"; }
msg_warn() { echo -e " ${YW}⚠ ${1}${CL}"; }

header_info() {
  clear 2>/dev/null || true
  cat <<"EOF"
    _       __________  __  __
   | |     / / __/ / / / / / /
   | | /| / / /_/ / /_/ / / /
   | |/ |/ / __/ / _, _/ /_/
   |__/|__/_/ /_/_/ |_|\____/

  WRU TGS Tracker
  Proxmox VE Helper Script Installer
EOF
  echo -e "\n${INFO} Repo: ${APP_GIT} (${APP_BRANCH})\n"
}

trap 'msg_error "Script failed near line $LINENO: $BASH_COMMAND"; exit 1' ERR

exit_script() {
  clear 2>/dev/null || true
  echo -e "\n${CROSS} ${RD}User exited script${CL}\n"
  exit 0
}

is_proxmox_host() {
  command -v pveversion >/dev/null 2>&1 && command -v pct >/dev/null 2>&1
}

ensure_root() {
  if [[ "$(id -u)" -ne 0 ]]; then
    msg_error "Must run as root on the Proxmox host"
    exit 1
  fi
}

ensure_whiptail() {
  if command -v whiptail >/dev/null 2>&1; then
    return 0
  fi
  msg_info "Installing whiptail"
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq whiptail >/dev/null
  msg_ok "whiptail installed"
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
  if command -v pvesh >/dev/null 2>&1; then
    pvesh get /cluster/nextid 2>/dev/null && return 0
  fi
  local id=100
  while pct status "$id" &>/dev/null; do
    id=$((id + 1))
  done
  echo "$id"
}

validate_container_id() {
  local id="$1"
  [[ "$id" =~ ^[0-9]+$ ]] || return 1
  ! pct status "$id" &>/dev/null && ! qm status "$id" &>/dev/null 2>&1
}

get_valid_container_id() {
  local id="$1"
  while ! validate_container_id "$id"; do
    id=$((id + 1))
  done
  echo "$id"
}

validate_hostname() {
  local hn="$1"
  [[ "$hn" =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$ ]] && ((${#hn} <= 253))
}

validate_ip_cidr() {
  local ip="$1"
  [[ "$ip" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}/([0-9]|[1-2][0-9]|3[0-2])$ ]] || return 1
  local addr="${ip%%/*}"
  local o
  IFS=. read -r -a o <<<"$addr"
  local n
  for n in "${o[@]}"; do
    ((n >= 0 && n <= 255)) || return 1
  done
  return 0
}

validate_gateway_ip() {
  local gw="$1"
  [[ "$gw" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || return 1
  local o
  IFS=. read -r -a o <<<"$gw"
  local n
  for n in "${o[@]}"; do
    ((n >= 0 && n <= 255)) || return 1
  done
  return 0
}

STORAGE_RESULT=""

select_storage() {
  local class="$1"
  local content content_label
  STORAGE_RESULT=""
  case "$class" in
  container)
    content="rootdir"
    content_label="Container"
    ;;
  template)
    content="vztmpl"
    content_label="Container template"
    ;;
  *)
    msg_error "Invalid storage class '$class'"
    exit 1
    ;;
  esac

  local -a menu=()
  local -A map=()
  local tag type total used free _
  while read -r tag type _ total used free _; do
    [[ -n "$tag" && -n "$type" ]] || continue
    local display="${tag} (${type})"
    local free_h used_h
    free_h="$(numfmt --to=iec --from-unit=1024 --format '%.1f' <<<"$free" 2>/dev/null || echo "$free")"
    used_h="$(numfmt --to=iec --from-unit=1024 --format '%.1f' <<<"$used" 2>/dev/null || echo "$used")"
    map["$display"]="$tag"
    menu+=("$display" "Free: ${free_h}B  Used: ${used_h}B" "OFF")
  done < <(pvesm status -content "$content" 2>/dev/null | awk 'NR>1')

  if [[ ${#menu[@]} -eq 0 ]]; then
    msg_error "No storage found for content type '$content'"
    exit 1
  fi

  if [[ $((${#menu[@]} / 3)) -eq 1 ]]; then
    STORAGE_RESULT="${map[${menu[0]}]}"
    return 0
  fi

  local selected
  selected=$(whiptail --backtitle "Proxmox VE Helper Scripts" \
    --title "Storage Pools" \
    --radiolist "Which storage pool for ${content_label,,}?\n(Spacebar to select)" \
    16 72 6 "${menu[@]}" 3>&1 1>&2 2>&3) || exit_script
  selected="${selected%"${selected##*[![:space:]]}"}"
  if [[ -z "$selected" || -z "${map[$selected]+x}" ]]; then
    msg_error "No valid storage selected"
    exit 1
  fi
  STORAGE_RESULT="${map[$selected]}"
}

base_settings() {
  CT_TYPE="${var_unprivileged}"
  DISK_SIZE="${var_disk}"
  CORE_COUNT="${var_cpu}"
  RAM_SIZE="${var_ram}"
  VERBOSE="${1:-${var_verbose:-no}}"
  CT_ID="${var_ctid:-$(next_ctid)}"
  if ! validate_container_id "$CT_ID"; then
    CT_ID="$(get_valid_container_id "$CT_ID")"
  fi
  HN="$(echo "${var_hostname,,}" | tr -d ' ')"
  BRG="${var_brg}"
  NET="${var_net}"
  if [[ "$NET" == "dhcp" ]]; then
    GATE=""
  elif [[ -n "$var_gateway" ]]; then
    GATE=",gw=${var_gateway}"
  else
    GATE=""
  fi
  # Accept legacy IP_CIDR / GW / NET=static from earlier WRU installer
  if [[ "${NET}" == "static" && -n "${IP_CIDR:-}" ]]; then
    NET="${IP_CIDR}"
    [[ -n "${GW:-}" ]] && GATE=",gw=${GW}"
  fi
  IPV6_METHOD="${var_ipv6_method}"
  IPV6_ADDR=""
  IPV6_GATE=""
  [[ -n "$var_mtu" ]] && MTU=",mtu=${var_mtu}" || MTU=""
  [[ -n "$var_searchdomain" ]] && SD="-searchdomain=${var_searchdomain}" || SD=""
  [[ -n "$var_ns" ]] && NS="-nameserver=${var_ns}" || NS=""
  [[ -n "$var_mac" ]] && MAC=",hwaddr=${var_mac}" || MAC=""
  [[ -n "$var_vlan" ]] && VLAN=",tag=${var_vlan}" || VLAN=""
  if [[ "${var_tags}" == *wru* ]]; then
    TAGS="${var_tags}"
  else
    TAGS="wru${var_tags:+;${var_tags}}"
  fi
  SSH="${var_ssh}"
  ENABLE_FUSE="${var_fuse}"
  ENABLE_TUN="${var_tun}"
  ENABLE_NESTING="${var_nesting}"
  ENABLE_KEYCTL="${var_keyctl}"
  [[ "$CT_TYPE" == "1" ]] && ENABLE_KEYCTL="1"
  PROTECT_CT="${var_protection}"
  CT_TIMEZONE="${var_timezone}"
  if [[ -z "$CT_TIMEZONE" ]]; then
    if command -v timedatectl >/dev/null 2>&1; then
      CT_TIMEZONE="$(timedatectl show --value --property=Timezone 2>/dev/null || true)"
    elif [[ -f /etc/timezone ]]; then
      CT_TIMEZONE="$(cat /etc/timezone)"
    fi
  fi
  [[ "${CT_TIMEZONE:-}" == Etc/* ]] && CT_TIMEZONE="host"
  if [[ -n "$var_pw" ]]; then
    PW="--password ${var_pw}"
    PW_DISPLAY="********"
  else
    PW=""
    PW_DISPLAY="Automatic Login"
  fi
  TEMPLATE_STORAGE="${var_template_storage}"
  CONTAINER_STORAGE="${var_container_storage}"
}

echo_default() {
  local ct_type_desc="Unprivileged"
  [[ "$CT_TYPE" == "0" ]] && ct_type_desc="Privileged"
  echo -e "${INFO}${BOLD}${DGN}Using Default Settings${CL}"
  echo -e "${INFO}${BOLD}${DGN}Container ID: ${BGN}${CT_ID}${CL}"
  echo -e "${INFO}${BOLD}${DGN}Operating System: ${BGN}${var_os} (${var_version})${CL}"
  echo -e "${INFO}${BOLD}${DGN}Container Type: ${BGN}${ct_type_desc}${CL}"
  echo -e "${INFO}${BOLD}${DGN}Disk Size: ${BGN}${DISK_SIZE} GB${CL}"
  echo -e "${INFO}${BOLD}${DGN}CPU Cores: ${BGN}${CORE_COUNT}${CL}"
  echo -e "${INFO}${BOLD}${DGN}RAM Size: ${BGN}${RAM_SIZE} MiB${CL}"
  echo -e "${INFO}${BOLD}${DGN}Network: ${BGN}${NET}${CL}"
  echo -e "${CREATING} ${GN}${APP} LXC using the above default settings${CL}\n"
}

# ---------------------------------------------------------------------------
# Advanced Settings — community-scripts style step wizard with Back navigation
# ---------------------------------------------------------------------------
advanced_settings() {
  local STEP=1
  local MAX_STEP=24
  local result=""

  local _ct_type="${CT_TYPE}"
  local _pw="$PW"
  local _pw_display="$PW_DISPLAY"
  local _ct_id="$CT_ID"
  local _hostname="$HN"
  local _disk_size="$DISK_SIZE"
  local _core_count="$CORE_COUNT"
  local _ram_size="$RAM_SIZE"
  local _bridge="$BRG"
  local _net="$NET"
  local _gate="$GATE"
  local _ipv6_method="$IPV6_METHOD"
  local _ipv6_addr="$IPV6_ADDR"
  local _ipv6_gate="$IPV6_GATE"
  local _mtu="${var_mtu}"
  local _sd="${var_searchdomain}"
  local _ns="${var_ns}"
  local _mac="${var_mac}"
  local _vlan="${var_vlan}"
  local _tags="$TAGS"
  local _ssh="$SSH"
  local _enable_fuse="$ENABLE_FUSE"
  local _enable_tun="$ENABLE_TUN"
  local _enable_nesting="$ENABLE_NESTING"
  local _enable_keyctl="$ENABLE_KEYCTL"
  local _protect_ct="$PROTECT_CT"
  local _ct_timezone="$CT_TIMEZONE"
  local _verbose="$VERBOSE"
  local _app_port="$APP_PORT"

  local -a BRIDGE_MENU_OPTIONS=()
  local b
  while IFS= read -r b; do
    [[ -n "$b" ]] && BRIDGE_MENU_OPTIONS+=("$b" " ")
  done < <(
    {
      awk '/^iface .* inet / && $2 ~ /^vmbr/ {print $2}' /etc/network/interfaces 2>/dev/null || true
      find /etc/network/interfaces.d -type f -exec awk '/^iface .* inet / && $2 ~ /^vmbr/ {print $2}' {} + 2>/dev/null || true
      ls /sys/class/net 2>/dev/null | grep -E '^vmbr' || true
    } | sort -u
  )
  if [[ ${#BRIDGE_MENU_OPTIONS[@]} -eq 0 ]]; then
    BRIDGE_MENU_OPTIONS+=("vmbr0" "Default bridge")
  fi

  step_inc() { STEP=$((STEP + 1)); }
  step_dec() { STEP=$((STEP - 1)); [[ $STEP -lt 1 ]] && exit_script; }

  while [[ $STEP -le $MAX_STEP ]]; do
    case $STEP in
    1)
      local default_on="ON" default_off="OFF"
      [[ "$_ct_type" == "0" ]] && {
        default_on="OFF"
        default_off="ON"
      }
      if result=$(whiptail --backtitle "Proxmox VE Helper Scripts [Step $STEP/$MAX_STEP]" \
        --title "CONTAINER TYPE" \
        --ok-button "Next" --cancel-button "Exit" \
        --radiolist "\nChoose container type:\n\nUse SPACE to select, ENTER to confirm." 14 58 2 \
        "1" "Unprivileged (recommended)" "$default_on" \
        "0" "Privileged" "$default_off" \
        3>&1 1>&2 2>&3); then
        [[ -n "$result" ]] && _ct_type="$result"
        step_inc
      else
        exit_script
      fi
      ;;
    2)
      local PW1 PW2
      if PW1=$(whiptail --backtitle "Proxmox VE Helper Scripts [Step $STEP/$MAX_STEP]" \
        --title "ROOT PASSWORD" \
        --ok-button "Next" --cancel-button "Back" \
        --passwordbox "\nSet Root Password (needed for root ssh access)\n\nLeave blank for automatic login (no password)" 12 58 \
        3>&1 1>&2 2>&3); then
        if [[ -z "$PW1" ]]; then
          _pw=""
          _pw_display="Automatic Login"
          step_inc
        elif [[ "$PW1" == *" "* ]]; then
          whiptail --msgbox "Password cannot contain spaces." 8 58
        elif ((${#PW1} < 5)); then
          whiptail --msgbox "Password must be at least 5 characters." 8 58
        elif PW2=$(whiptail --backtitle "Proxmox VE Helper Scripts [Step $STEP/$MAX_STEP]" \
          --title "PASSWORD VERIFICATION" \
          --ok-button "Confirm" --cancel-button "Back" \
          --passwordbox "\nVerify Root Password" 10 58 \
          3>&1 1>&2 2>&3); then
          if [[ "$PW1" == "$PW2" ]]; then
            _pw="--password $PW1"
            _pw_display="********"
            step_inc
          else
            whiptail --msgbox "Passwords do not match. Please try again." 8 58
          fi
        else
          step_dec
        fi
      else
        step_dec
      fi
      ;;
    3)
      if result=$(whiptail --backtitle "Proxmox VE Helper Scripts [Step $STEP/$MAX_STEP]" \
        --title "CONTAINER ID" \
        --ok-button "Next" --cancel-button "Back" \
        --inputbox "\nSet Container ID" 10 58 "$_ct_id" \
        3>&1 1>&2 2>&3); then
        local input_id="${result:-$_ct_id}"
        if ! [[ "$input_id" =~ ^[0-9]+$ ]]; then
          whiptail --msgbox "Container ID must be numeric." 8 58
          continue
        fi
        if ! validate_container_id "$input_id"; then
          local next_ok
          next_ok="$(get_valid_container_id "$input_id")"
          if whiptail --yesno "Container/VM ID $input_id is already in use.\n\nUse next available ID ($next_ok)?" 10 58; then
            _ct_id="$next_ok"
            step_inc
          fi
        else
          _ct_id="$input_id"
          step_inc
        fi
      else
        step_dec
      fi
      ;;
    4)
      if result=$(whiptail --backtitle "Proxmox VE Helper Scripts [Step $STEP/$MAX_STEP]" \
        --title "HOSTNAME" \
        --ok-button "Next" --cancel-button "Back" \
        --inputbox "\nSet Hostname (or FQDN, e.g. host.example.com)" 10 58 "$_hostname" \
        3>&1 1>&2 2>&3); then
        local hn_test
        hn_test="$(echo "${result:-$_hostname}" | tr '[:upper:]' '[:lower:]' | tr -d ' ')"
        if validate_hostname "$hn_test"; then
          _hostname="$hn_test"
          step_inc
        else
          whiptail --msgbox "Invalid hostname: '$hn_test'\n\nUse lowercase letters, digits, dots and hyphens." 12 60
        fi
      else
        step_dec
      fi
      ;;
    5)
      if result=$(whiptail --backtitle "Proxmox VE Helper Scripts [Step $STEP/$MAX_STEP]" \
        --title "DISK SIZE" \
        --ok-button "Next" --cancel-button "Back" \
        --inputbox "\nSet Disk Size in GB\n(App default: ${var_disk})" 10 58 "$_disk_size" \
        3>&1 1>&2 2>&3); then
        local disk_test="${result:-$_disk_size}"
        if [[ "$disk_test" =~ ^[1-9][0-9]*$ ]]; then
          _disk_size="$disk_test"
          step_inc
        else
          whiptail --msgbox "Disk size must be a positive integer!" 8 58
        fi
      else
        step_dec
      fi
      ;;
    6)
      if result=$(whiptail --backtitle "Proxmox VE Helper Scripts [Step $STEP/$MAX_STEP]" \
        --title "CPU CORES" \
        --ok-button "Next" --cancel-button "Back" \
        --inputbox "\nAllocate CPU Cores\n(App default: ${var_cpu})" 10 58 "$_core_count" \
        3>&1 1>&2 2>&3); then
        local cpu_test="${result:-$_core_count}"
        if [[ "$cpu_test" =~ ^[1-9][0-9]*$ ]]; then
          _core_count="$cpu_test"
          step_inc
        else
          whiptail --msgbox "CPU core count must be a positive integer!" 8 58
        fi
      else
        step_dec
      fi
      ;;
    7)
      if result=$(whiptail --backtitle "Proxmox VE Helper Scripts [Step $STEP/$MAX_STEP]" \
        --title "RAM SIZE" \
        --ok-button "Next" --cancel-button "Back" \
        --inputbox "\nAllocate RAM in MiB\n(App default: ${var_ram})" 10 58 "$_ram_size" \
        3>&1 1>&2 2>&3); then
        local ram_test="${result:-$_ram_size}"
        if [[ "$ram_test" =~ ^[1-9][0-9]*$ ]]; then
          _ram_size="$ram_test"
          step_inc
        else
          whiptail --msgbox "RAM size must be a positive integer!" 8 58
        fi
      else
        step_dec
      fi
      ;;
    8)
      if result=$(whiptail --backtitle "Proxmox VE Helper Scripts [Step $STEP/$MAX_STEP]" \
        --title "NETWORK BRIDGE" \
        --ok-button "Next" --cancel-button "Back" \
        --menu "\nSelect network bridge:" 16 58 6 \
        "${BRIDGE_MENU_OPTIONS[@]}" \
        3>&1 1>&2 2>&3); then
        _bridge="${result:-vmbr0}"
        step_inc
      else
        step_dec
      fi
      ;;
    9)
      if result=$(whiptail --backtitle "Proxmox VE Helper Scripts [Step $STEP/$MAX_STEP]" \
        --title "IPv4 CONFIGURATION" \
        --ok-button "Next" --cancel-button "Back" \
        --menu "\nSelect IPv4 Address Assignment:" 14 65 2 \
        "dhcp" "Automatic (DHCP, recommended)" \
        "static" "Static (manual CIDR + gateway)" \
        3>&1 1>&2 2>&3); then
        if [[ "$result" == "static" ]]; then
          local static_ip gateway_ip
          if static_ip=$(whiptail --backtitle "Proxmox VE Helper Scripts [Step $STEP/$MAX_STEP]" \
            --title "STATIC IPv4 ADDRESS" \
            --ok-button "Next" --cancel-button "Back" \
            --inputbox "\nEnter Static IPv4 CIDR Address\n(e.g. 192.168.1.100/24)" 12 58 \
            "${_net/dhcp/}" \
            3>&1 1>&2 2>&3); then
            if validate_ip_cidr "$static_ip"; then
              if gateway_ip=$(whiptail --backtitle "Proxmox VE Helper Scripts [Step $STEP/$MAX_STEP]" \
                --title "GATEWAY IP" \
                --ok-button "Next" --cancel-button "Back" \
                --inputbox "\nEnter Gateway IP address" 10 58 \
                "${_gate#,gw=}" \
                3>&1 1>&2 2>&3); then
                if validate_gateway_ip "$gateway_ip"; then
                  _net="$static_ip"
                  _gate=",gw=$gateway_ip"
                  step_inc
                else
                  whiptail --msgbox "Invalid gateway IP: $gateway_ip" 8 58
                fi
              else
                continue
              fi
            else
              whiptail --msgbox "Invalid IPv4 CIDR.\nExample: 192.168.1.100/24" 10 58
            fi
          else
            continue
          fi
        else
          _net="dhcp"
          _gate=""
          step_inc
        fi
      else
        step_dec
      fi
      ;;
    10)
      if result=$(whiptail --backtitle "Proxmox VE Helper Scripts [Step $STEP/$MAX_STEP]" \
        --title "IPv6 CONFIGURATION" \
        --ok-button "Next" --cancel-button "Back" \
        --menu "\nSelect IPv6 Address Assignment:" 16 65 4 \
        "auto" "SLAAC (auto)" \
        "dhcp" "DHCPv6" \
        "static" "Static IPv6" \
        "none" "Disable IPv6" \
        3>&1 1>&2 2>&3); then
        _ipv6_method="$result"
        _ipv6_addr=""
        _ipv6_gate=""
        if [[ "$result" == "static" ]]; then
          local v6a v6g
          if v6a=$(whiptail --backtitle "Proxmox VE Helper Scripts [Step $STEP/$MAX_STEP]" \
            --title "STATIC IPv6 ADDRESS" \
            --ok-button "Next" --cancel-button "Back" \
            --inputbox "\nEnter Static IPv6 CIDR\n(e.g. 2001:db8::10/64)" 12 58 \
            3>&1 1>&2 2>&3); then
            if v6g=$(whiptail --backtitle "Proxmox VE Helper Scripts [Step $STEP/$MAX_STEP]" \
              --title "IPv6 GATEWAY" \
              --ok-button "Next" --cancel-button "Back" \
              --inputbox "\nEnter IPv6 Gateway (optional)" 10 58 \
              3>&1 1>&2 2>&3); then
              _ipv6_addr="$v6a"
              _ipv6_gate="$v6g"
              step_inc
            else
              continue
            fi
          else
            continue
          fi
        else
          step_inc
        fi
      else
        step_dec
      fi
      ;;
    11)
      if result=$(whiptail --backtitle "Proxmox VE Helper Scripts [Step $STEP/$MAX_STEP]" \
        --title "MTU SIZE" \
        --ok-button "Next" --cancel-button "Back" \
        --inputbox "\nSet MTU Size (leave blank for default)" 10 58 "$_mtu" \
        3>&1 1>&2 2>&3); then
        _mtu="$result"
        step_inc
      else
        step_dec
      fi
      ;;
    12)
      if result=$(whiptail --backtitle "Proxmox VE Helper Scripts [Step $STEP/$MAX_STEP]" \
        --title "DNS SEARCH DOMAIN" \
        --ok-button "Next" --cancel-button "Back" \
        --inputbox "\nSet DNS Search Domain (leave blank for host default)" 10 58 "$_sd" \
        3>&1 1>&2 2>&3); then
        _sd="$result"
        step_inc
      else
        step_dec
      fi
      ;;
    13)
      if result=$(whiptail --backtitle "Proxmox VE Helper Scripts [Step $STEP/$MAX_STEP]" \
        --title "DNS SERVER" \
        --ok-button "Next" --cancel-button "Back" \
        --inputbox "\nSet DNS Server IP (leave blank for host default)" 10 58 "$_ns" \
        3>&1 1>&2 2>&3); then
        _ns="$result"
        step_inc
      else
        step_dec
      fi
      ;;
    14)
      if result=$(whiptail --backtitle "Proxmox VE Helper Scripts [Step $STEP/$MAX_STEP]" \
        --title "MAC ADDRESS" \
        --ok-button "Next" --cancel-button "Back" \
        --inputbox "\nSet MAC Address (leave blank to auto-generate)" 10 58 "$_mac" \
        3>&1 1>&2 2>&3); then
        _mac="$result"
        step_inc
      else
        step_dec
      fi
      ;;
    15)
      if result=$(whiptail --backtitle "Proxmox VE Helper Scripts [Step $STEP/$MAX_STEP]" \
        --title "VLAN TAG" \
        --ok-button "Next" --cancel-button "Back" \
        --inputbox "\nSet VLAN Tag (leave blank for none)" 10 58 "$_vlan" \
        3>&1 1>&2 2>&3); then
        _vlan="$result"
        step_inc
      else
        step_dec
      fi
      ;;
    16)
      if result=$(whiptail --backtitle "Proxmox VE Helper Scripts [Step $STEP/$MAX_STEP]" \
        --title "TAGS" \
        --ok-button "Next" --cancel-button "Back" \
        --inputbox "\nSet Container Tags (semicolon-separated)" 10 58 "$_tags" \
        3>&1 1>&2 2>&3); then
        _tags="${result:-wru}"
        step_inc
      else
        step_dec
      fi
      ;;
    17)
      local ssh_flag="--defaultno"
      [[ "$_ssh" == "yes" ]] && ssh_flag=""
      if whiptail --backtitle "Proxmox VE Helper Scripts [Step $STEP/$MAX_STEP]" \
        --title "SSH ACCESS" \
        --ok-button "Next" --cancel-button "Back" \
        $ssh_flag \
        --yesno "\nEnable root SSH login in the container?\n\n(App default: ${var_ssh})" 12 58; then
        _ssh="yes"
        step_inc
      else
        local rc=$?
        if [[ $rc -eq 1 ]]; then
          _ssh="no"
          step_inc
        else
          step_dec
        fi
      fi
      ;;
    18)
      local fuse_flag="--defaultno"
      [[ "$_enable_fuse" == "yes" ]] && fuse_flag=""
      if whiptail --backtitle "Proxmox VE Helper Scripts [Step $STEP/$MAX_STEP]" \
        --title "FUSE SUPPORT" \
        --ok-button "Next" --cancel-button "Back" \
        $fuse_flag \
        --yesno "\nEnable FUSE?\n\nNeeded for rclone, mergerfs, AppImage, SSHFS.\n\n(App default: ${var_fuse})" 14 58; then
        _enable_fuse="yes"
        step_inc
      else
        local rc=$?
        if [[ $rc -eq 1 ]]; then
          _enable_fuse="no"
          step_inc
        else
          step_dec
        fi
      fi
      ;;
    19)
      local tun_flag="--defaultno"
      [[ "$_enable_tun" == "yes" ]] && tun_flag=""
      if whiptail --backtitle "Proxmox VE Helper Scripts [Step $STEP/$MAX_STEP]" \
        --title "TUN/TAP SUPPORT" \
        --ok-button "Next" --cancel-button "Back" \
        $tun_flag \
        --yesno "\nEnable TUN/TAP?\n\nNeeded for WireGuard, OpenVPN, Tailscale.\n\n(App default: ${var_tun})" 14 58; then
        _enable_tun="yes"
        step_inc
      else
        local rc=$?
        if [[ $rc -eq 1 ]]; then
          _enable_tun="no"
          step_inc
        else
          step_dec
        fi
      fi
      ;;
    20)
      local nesting_flag=""
      [[ "$_enable_nesting" == "0" || "$_enable_nesting" == "no" ]] && nesting_flag="--defaultno"
      if whiptail --backtitle "Proxmox VE Helper Scripts [Step $STEP/$MAX_STEP]" \
        --title "NESTING SUPPORT" \
        --ok-button "Next" --cancel-button "Back" \
        $nesting_flag \
        --yesno "\nEnable Nesting?\n\nRequired for Docker / Podman / nested LXC.\n\n(App default: ${var_nesting})" 14 58; then
        _enable_nesting="1"
        step_inc
      else
        local rc=$?
        if [[ $rc -eq 1 ]]; then
          _enable_nesting="0"
          step_inc
        else
          step_dec
        fi
      fi
      ;;
    21)
      if [[ "$_ct_type" == "1" ]]; then
        _enable_keyctl="1"
        step_inc
        continue
      fi
      local keyctl_flag="--defaultno"
      [[ "$_enable_keyctl" == "1" ]] && keyctl_flag=""
      if whiptail --backtitle "Proxmox VE Helper Scripts [Step $STEP/$MAX_STEP]" \
        --title "KEYCTL SUPPORT" \
        --ok-button "Next" --cancel-button "Back" \
        $keyctl_flag \
        --yesno "\nEnable Keyctl?\n\nNeeded for Docker / systemd-networkd.\n\n(App default: ${var_keyctl})" 14 58; then
        _enable_keyctl="1"
        step_inc
      else
        local rc=$?
        if [[ $rc -eq 1 ]]; then
          _enable_keyctl="0"
          step_inc
        else
          step_dec
        fi
      fi
      ;;
    22)
      if result=$(whiptail --backtitle "Proxmox VE Helper Scripts [Step $STEP/$MAX_STEP]" \
        --title "CONTAINER TIMEZONE" \
        --ok-button "Next" --cancel-button "Back" \
        --inputbox "\nSet container timezone (e.g. Australia/Sydney).\nLeave empty to inherit host.\n\nCurrent: ${_ct_timezone:-host}" 14 62 "$_ct_timezone" \
        3>&1 1>&2 2>&3); then
        _ct_timezone="$result"
        [[ "${_ct_timezone:-}" == Etc/* ]] && _ct_timezone="host"
        step_inc
      else
        step_dec
      fi
      ;;
    23)
      local protect_flag="--defaultno"
      [[ "$_protect_ct" == "yes" || "$_protect_ct" == "1" ]] && protect_flag=""
      if whiptail --backtitle "Proxmox VE Helper Scripts [Step $STEP/$MAX_STEP]" \
        --title "CONTAINER PROTECTION" \
        --ok-button "Next" --cancel-button "Back" \
        $protect_flag \
        --yesno "\nEnable container protection?\n\nPrevents accidental deletion/stop from the UI." 12 58; then
        _protect_ct="yes"
        step_inc
      else
        local rc=$?
        if [[ $rc -eq 1 ]]; then
          _protect_ct="no"
          step_inc
        else
          step_dec
        fi
      fi
      ;;
    24)
      if result=$(whiptail --backtitle "Proxmox VE Helper Scripts [Step $STEP/$MAX_STEP]" \
        --title "WRU APP PORT" \
        --ok-button "Next" --cancel-button "Back" \
        --inputbox "\nHTTP listen port for WRU\n(App default: 8000)" 10 58 "$_app_port" \
        3>&1 1>&2 2>&3); then
        if [[ "$result" =~ ^[1-9][0-9]{0,4}$ ]] && ((result <= 65535)); then
          _app_port="$result"
        else
          whiptail --msgbox "Port must be 1–65535." 8 58
          continue
        fi
      else
        step_dec
        continue
      fi

      local verbose_flag="--defaultno"
      [[ "$_verbose" == "yes" ]] && verbose_flag=""
      if whiptail --backtitle "Proxmox VE Helper Scripts [Step $STEP/$MAX_STEP]" \
        --title "VERBOSE MODE" \
        $verbose_flag \
        --yesno "\nEnable Verbose Mode?\n\nShows detailed output during installation." 12 58; then
        _verbose="yes"
      else
        _verbose="no"
      fi

      local ct_type_desc="Unprivileged"
      [[ "$_ct_type" == "0" ]] && ct_type_desc="Privileged"
      local nesting_desc="Disabled"
      [[ "$_enable_nesting" == "1" ]] && nesting_desc="Enabled"
      local keyctl_desc="Disabled"
      [[ "$_enable_keyctl" == "1" ]] && keyctl_desc="Enabled"
      local protect_desc="No"
      [[ "$_protect_ct" == "yes" || "$_protect_ct" == "1" ]] && protect_desc="Yes"
      local ipv4_desc="$_net"
      [[ -n "$_gate" ]] && ipv4_desc="${_net} ${_gate#,}"

      local summary
      summary="Container Type: $ct_type_desc
Container ID: $_ct_id
Hostname: $_hostname
Root Password: $_pw_display

Resources:
  Disk: ${_disk_size} GB
  CPU: ${_core_count} cores
  RAM: ${_ram_size} MiB

Network:
  Bridge: $_bridge
  IPv4: $ipv4_desc
  IPv6: $_ipv6_method
  MTU: ${_mtu:-(default)}  VLAN: ${_vlan:-(none)}
  DNS: ${_ns:-(host)}  Search: ${_sd:-(host)}
  MAC: ${_mac:-(auto)}

Features:
  FUSE: $_enable_fuse | TUN: $_enable_tun
  Nesting: $nesting_desc | Keyctl: $keyctl_desc
  SSH root: $_ssh | Protection: $protect_desc
  Timezone: ${_ct_timezone:-host}

App:
  Port: $_app_port
  Verbose: $_verbose"

      if whiptail --backtitle "Proxmox VE Helper Scripts [Step $STEP/$MAX_STEP]" \
        --title "CONFIRM SETTINGS" \
        --ok-button "Create LXC" --cancel-button "Back" \
        --yesno "$summary\n\nCreate ${APP} LXC with these settings?" 28 62; then
        step_inc
      else
        step_dec
      fi
      ;;
    esac
  done

  CT_TYPE="$_ct_type"
  PW="$_pw"
  PW_DISPLAY="$_pw_display"
  CT_ID="$_ct_id"
  HN="$_hostname"
  DISK_SIZE="$_disk_size"
  CORE_COUNT="$_core_count"
  RAM_SIZE="$_ram_size"
  BRG="$_bridge"
  NET="$_net"
  GATE="$_gate"
  IPV6_METHOD="$_ipv6_method"
  IPV6_ADDR="$_ipv6_addr"
  IPV6_GATE="$_ipv6_gate"
  TAGS="$_tags"
  SSH="$_ssh"
  ENABLE_FUSE="$_enable_fuse"
  ENABLE_TUN="$_enable_tun"
  ENABLE_NESTING="$_enable_nesting"
  ENABLE_KEYCTL="$_enable_keyctl"
  PROTECT_CT="$_protect_ct"
  CT_TIMEZONE="$_ct_timezone"
  VERBOSE="$_verbose"
  APP_PORT="$_app_port"
  [[ -n "$_mtu" ]] && MTU=",mtu=$_mtu" || MTU=""
  [[ -n "$_sd" ]] && SD="-searchdomain=$_sd" || SD=""
  [[ -n "$_ns" ]] && NS="-nameserver=$_ns" || NS=""
  [[ -n "$_mac" ]] && MAC=",hwaddr=$_mac" || MAC=""
  [[ -n "$_vlan" ]] && VLAN=",tag=$_vlan" || VLAN=""
}

install_menu() {
  ensure_whiptail
  local choice="${mode:-}"
  if [[ -z "$choice" && "$NONINTERACTIVE" != "1" && -t 0 ]]; then
    choice=$(whiptail --backtitle "Proxmox VE Helper Scripts" \
      --title "WRU Options" \
      --ok-button "Select" --cancel-button "Exit Script" \
      --notags \
      --menu "\nChoose an option:\n Use TAB or Arrow keys to navigate, ENTER to select.\n" \
      18 68 5 \
      "1" "Default Install" \
      "2" "Advanced Install" \
      "3" "Update existing CT from GitHub" \
      --default-item "1" \
      3>&1 1>&2 2>&3) || exit_script
  elif [[ -z "$choice" ]]; then
    choice="1"
  fi

  case "$choice" in
  1 | default | DEFAULT)
    header_info
    echo -e "${DEFAULT}${BOLD}${BL}Using Default Settings${CL}"
    METHOD="default"
    base_settings "no"
    echo_default
    ;;
  2 | advanced | ADVANCED)
    header_info
    echo -e "${ADVANCED}${BOLD}${RD}Using Advanced Install${CL}"
    METHOD="advanced"
    base_settings
    advanced_settings
    ;;
  3 | update | UPDATE)
    METHOD="update"
    ;;
  *)
    msg_error "Invalid option: $choice"
    exit 1
    ;;
  esac
}

list_wru_candidate_cts() {
  # Prefer CTs that already have /opt/wru; also include hostname/tag matches
  local id status hn
  while read -r id status; do
    [[ "$id" =~ ^[0-9]+$ ]] || continue
    [[ "$status" == "running" || "$status" == "stopped" ]] || continue
    hn="$(pct config "$id" 2>/dev/null | awk -F': ' '/^hostname:/{print $2; exit}')"
    if pct exec "$id" -- test -d /opt/wru >/dev/null 2>&1; then
      echo "$id|$hn|installed"
      continue
    fi
    if [[ "${hn,,}" == *wru* ]] || pct config "$id" 2>/dev/null | grep -qi 'tags:.*wru'; then
      echo "$id|$hn|candidate"
    fi
  done < <(pct list 2>/dev/null | awk 'NR>1 {print $1, $2}')
}

pick_update_ct() {
  local -a menu=()
  local line id hn kind
  while IFS='|' read -r id hn kind; do
    [[ -n "$id" ]] || continue
    menu+=("$id" "${hn:-ct$id} (${kind})")
  done < <(list_wru_candidate_cts)

  if [[ ${#menu[@]} -eq 0 ]]; then
    # Fallback: list all running CTs
    while read -r id status hn; do
      [[ "$status" == "running" ]] || continue
      menu+=("$id" "${hn:-ct$id}")
    done < <(pct list 2>/dev/null | awk 'NR>1 {print $1, $2, $3}')
  fi

  if [[ ${#menu[@]} -eq 0 ]]; then
    msg_error "No LXC containers found to update"
    exit 1
  fi

  if [[ -n "${var_ctid:-${CTID:-}}" ]]; then
    CT_ID="${var_ctid:-$CTID}"
    if ! pct status "$CT_ID" &>/dev/null; then
      msg_error "CT ${CT_ID} not found"
      exit 1
    fi
    return 0
  fi

  if [[ "$NONINTERACTIVE" == "1" || ! -t 0 ]]; then
    CT_ID="${menu[0]}"
    return 0
  fi

  CT_ID=$(whiptail --backtitle "Proxmox VE Helper Scripts" \
    --title "Update WRU CT" \
    --ok-button "Update" --cancel-button "Exit" \
    --menu "\nSelect the WRU container to update from GitHub:\n(DB + uploads are kept)" \
    18 70 8 \
    "${menu[@]}" \
    3>&1 1>&2 2>&3) || exit_script
}

update_existing_ct() {
  ensure_root
  header_info
  echo -e "${INFO}${BOLD}${BL}Update existing CT from GitHub${CL}\n"
  echo -e "Repo: ${APP_GIT}  Branch: ${APP_BRANCH}\n"

  pick_update_ct

  if ! pct status "$CT_ID" &>/dev/null; then
    msg_error "CT ${CT_ID} does not exist"
    exit 1
  fi

  local st
  st="$(pct status "$CT_ID" 2>/dev/null | awk '{print $2}')"
  if [[ "$st" != "running" ]]; then
    msg_info "Starting CT ${CT_ID}"
    pct start "$CT_ID" >/dev/null
    sleep 3
    msg_ok "Started CT ${CT_ID}"
  fi

  # Optional branch/repo prompts
  if [[ "$NONINTERACTIVE" != "1" && -t 0 ]]; then
    local br repo
    br=$(whiptail --backtitle "Proxmox VE Helper Scripts" \
      --title "Git branch" \
      --inputbox "Branch to pull:" 10 60 "$APP_BRANCH" \
      3>&1 1>&2 2>&3) || exit_script
    APP_BRANCH="${br:-$APP_BRANCH}"
    RAW_BASE="${WRU_RAW_BASE:-https://raw.githubusercontent.com/McKrackenAU/WRU/${APP_BRANCH}}"
    repo=$(whiptail --backtitle "Proxmox VE Helper Scripts" \
      --title "Git repository" \
      --inputbox "Git clone URL:" 10 72 "$APP_GIT" \
      3>&1 1>&2 2>&3) || exit_script
    APP_GIT="${repo:-$APP_GIT}"
  fi

  msg_info "Fetching install script from GitHub (${APP_BRANCH})"
  local host_tmp ct_tmp
  host_tmp="$(mktemp)"
  ct_tmp="/tmp/wru-install.sh"
  # Always prefer live GitHub for updates so the host checkout isn't required
  curl -fsSL "${RAW_BASE}/install/wru-install.sh" -o "$host_tmp"
  chmod +x "$host_tmp"
  msg_ok "Fetched install script"

  msg_info "Updating ${APP} inside CT ${CT_ID}"
  pct push "$CT_ID" "$host_tmp" "$ct_tmp"
  pct exec "$CT_ID" -- chmod +x "$ct_tmp"
  # Discover current app port if set
  local port_in_ct
  port_in_ct="$(pct exec "$CT_ID" -- bash -c 'source /etc/default/wru 2>/dev/null; echo "${WRU_PORT:-}"' 2>/dev/null || true)"
  APP_PORT="${port_in_ct:-$APP_PORT}"

  set +e
  pct exec "$CT_ID" -- env \
    WRU_REPO="$APP_GIT" \
    WRU_BRANCH="$APP_BRANCH" \
    WRU_PORT="$APP_PORT" \
    bash "$ct_tmp"
  local rc=$?
  set -e
  rm -f "$host_tmp"
  if [[ "$rc" -ne 0 ]]; then
    msg_error "Update inside CT ${CT_ID} failed (exit ${rc})"
    exit "$rc"
  fi
  msg_ok "Updated ${APP}"

  # Ensure in-app updater helper exists even on older install paths
  pct exec "$CT_ID" -- bash -c '
    set -e
    if [[ -f /opt/wru/scripts/wru-update.sh ]]; then
      install -m 755 /opt/wru/scripts/wru-update.sh /usr/local/sbin/wru-update
      cat >/etc/sudoers.d/wru-update <<EOF
wru ALL=(root) NOPASSWD: /usr/local/sbin/wru-update
wru ALL=(root) NOPASSWD: /usr/bin/systemd-run
wru ALL=(root) NOPASSWD: /bin/systemctl reset-failed wru-online-update.service
EOF
      chmod 440 /etc/sudoers.d/wru-update
    fi
  ' || true

  local ip
  ip="$(pct exec "$CT_ID" -- hostname -I | awk '{print $1}')"
  echo
  msg_ok "GitHub update complete for CT ${CT_ID}"
  echo -e "${INFO}${YW} Access URL:${CL} ${BGN}http://${ip}:${APP_PORT}${CL}"
  echo -e "${INFO}${YW} In-app updater:${CL} ${BL}http://${ip}:${APP_PORT}/system${CL}"
  echo -e "${INFO}${YW} CLI updater:${CL} ${BL}pct exec ${CT_ID} -- sudo -u wru sudo /usr/local/sbin/wru-update${CL}"
  echo -e "${INFO} Or inside the CT as root: ${BL}wru-update${CL}\n"
}

ensure_template() {
  local storage_tmpl="${TEMPLATE_STORAGE:-local}"
  if [[ -z "$TEMPLATE_STORAGE" ]]; then
    if pvesm status -content vztmpl 2>/dev/null | awk 'NR>1 {print $1}' | grep -qx local; then
      storage_tmpl="local"
    else
      storage_tmpl="$(pvesm status -content vztmpl 2>/dev/null | awk 'NR>1 {print $1; exit}')"
      storage_tmpl="${storage_tmpl:-local}"
    fi
  fi
  TEMPLATE_STORAGE="$storage_tmpl"

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

  if ! pveam list "$TEMPLATE_STORAGE" 2>/dev/null | grep -Fq "$available"; then
    msg_info "Downloading ${available}"
    pveam download "$TEMPLATE_STORAGE" "$available" >/dev/null
    msg_ok "Downloaded template"
  else
    msg_ok "Template already present"
  fi
  TEMPLATE_PATH="${TEMPLATE_STORAGE}:vztmpl/${available}"
}

build_net0() {
  local net="name=eth0,bridge=${BRG},ip=${NET}"
  [[ -n "$GATE" ]] && net+="${GATE}"
  [[ -n "$MAC" ]] && net+="${MAC}"
  [[ -n "$VLAN" ]] && net+="${VLAN}"
  [[ -n "$MTU" ]] && net+="${MTU}"
  case "$IPV6_METHOD" in
  auto) net+=",ip6=auto" ;;
  dhcp) net+=",ip6=dhcp" ;;
  static)
    [[ -n "$IPV6_ADDR" ]] && net+=",ip6=${IPV6_ADDR}"
    [[ -n "$IPV6_GATE" ]] && net+=",gw6=${IPV6_GATE}"
    ;;
  none) ;;
  esac
  echo "$net"
}

build_features() {
  local features=""
  [[ "$ENABLE_NESTING" == "1" || "$ENABLE_NESTING" == "yes" ]] && features="nesting=1"
  if [[ "$CT_TYPE" == "1" || "$ENABLE_KEYCTL" == "1" ]]; then
    [[ -n "$features" ]] && features+=","
    features+="keyctl=1"
  fi
  if [[ "$ENABLE_FUSE" == "yes" ]]; then
    [[ -n "$features" ]] && features+=","
    features+="fuse=1"
  fi
  echo "$features"
}

apply_tun() {
  [[ "$ENABLE_TUN" == "yes" ]] || return 0
  local conf="/etc/pve/lxc/${CT_ID}.conf"
  {
    echo "lxc.cgroup2.devices.allow: c 10:200 rwm"
    echo "lxc.mount.entry: /dev/net/tun dev/net/tun none bind,create=file"
  } >>"$conf"
}

enable_ssh_in_ct() {
  [[ "$SSH" == "yes" ]] || return 0
  pct exec "$CT_ID" -- bash -c '
    sed -i "s/^#\?PermitRootLogin.*/PermitRootLogin yes/" /etc/ssh/sshd_config
    sed -i "s/^#\?PasswordAuthentication.*/PasswordAuthentication yes/" /etc/ssh/sshd_config
    systemctl enable --now ssh >/dev/null 2>&1 || systemctl enable --now sshd >/dev/null 2>&1 || true
  ' || true
}

create_and_install() {
  ensure_root

  if [[ -z "$CONTAINER_STORAGE" ]]; then
    if [[ "$NONINTERACTIVE" == "1" || ! -t 0 ]]; then
      CONTAINER_STORAGE="$(pvesm status -content rootdir 2>/dev/null | awk 'NR>1 {print $1; exit}')"
    else
      select_storage container
      CONTAINER_STORAGE="$STORAGE_RESULT"
    fi
  fi
  if [[ -z "$CONTAINER_STORAGE" ]]; then
    msg_error "No container storage selected"
    exit 1
  fi

  if [[ -z "$TEMPLATE_STORAGE" && "$NONINTERACTIVE" != "1" && -t 0 ]]; then
    select_storage template
    TEMPLATE_STORAGE="$STORAGE_RESULT"
  fi

  ensure_template

  if pct status "$CT_ID" &>/dev/null; then
    msg_error "CT ${CT_ID} already exists"
    exit 1
  fi

  local net0 features
  net0="$(build_net0)"
  features="$(build_features)"

  local -a pct_args=(
    "$CT_ID" "$TEMPLATE_PATH"
    --hostname "$HN"
    --cores "$CORE_COUNT"
    --memory "$RAM_SIZE"
    --rootfs "${CONTAINER_STORAGE}:${DISK_SIZE}"
    --net0 "$net0"
    --unprivileged "$CT_TYPE"
    --onboot 1
    --start 0
  )
  [[ -n "$features" ]] && pct_args+=(--features "$features")
  [[ -n "$TAGS" ]] && pct_args+=(--tags "$TAGS")
  [[ -n "$SD" ]] && pct_args+=(--searchdomain "${SD#-searchdomain=}")
  [[ -n "$NS" ]] && pct_args+=(--nameserver "${NS#-nameserver=}")
  if [[ -n "$PW" ]]; then
    pct_args+=(--password "${PW#--password }")
  fi
  if [[ -n "$CT_TIMEZONE" ]]; then
    pct_args+=(--timezone "$CT_TIMEZONE")
  fi
  if [[ "$PROTECT_CT" == "yes" || "$PROTECT_CT" == "1" ]]; then
    pct_args+=(--protection 1)
  fi

  msg_info "Creating LXC ${CT_ID}"
  if [[ "$VERBOSE" == "yes" ]]; then
    pct create "${pct_args[@]}"
  else
    pct create "${pct_args[@]}" >/dev/null
  fi
  msg_ok "Created LXC ${CT_ID}"

  apply_tun
  pct start "$CT_ID" >/dev/null
  msg_ok "Started LXC ${CT_ID}"

  msg_info "Waiting for network"
  local ready=0
  local _
  for _ in $(seq 1 60); do
    if pct exec "$CT_ID" -- bash -c 'ping -c1 -W1 1.1.1.1 >/dev/null 2>&1 || ping -c1 -W1 8.8.8.8 >/dev/null 2>&1'; then
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

  enable_ssh_in_ct

  msg_info "Installing ${APP} inside CT ${CT_ID}"
  local host_tmp ct_tmp
  host_tmp="$(mktemp)"
  ct_tmp="/tmp/wru-install.sh"
  fetch_install_script_to "$host_tmp"
  pct push "$CT_ID" "$host_tmp" "$ct_tmp"
  pct exec "$CT_ID" -- chmod +x "$ct_tmp"
  local install_env=(
    WRU_REPO="$APP_GIT"
    WRU_BRANCH="$APP_BRANCH"
    WRU_PORT="$APP_PORT"
  )
  set +e
  pct exec "$CT_ID" -- env "${install_env[@]}" bash "$ct_tmp"
  local install_rc=$?
  set -e
  rm -f "$host_tmp"
  if [[ "$install_rc" -ne 0 ]]; then
    msg_error "Install inside CT ${CT_ID} failed (exit ${install_rc}). Check: pct enter ${CT_ID}"
    exit "$install_rc"
  fi
  msg_ok "Installed ${APP}"

  local ip
  if [[ "$NET" != "dhcp" ]]; then
    ip="${NET%%/*}"
  else
    ip="$(pct exec "$CT_ID" -- hostname -I | awk '{print $1}')"
  fi
  pct set "$CT_ID" -description $'WRU TGS Tracker\nURL: http://'"${ip}"':'"${APP_PORT}"$'\nRepo: '"${APP_GIT}"$'\nBranch: '"${APP_BRANCH}" >/dev/null || true

  echo
  msg_ok "Completed successfully!"
  echo -e " ${HOLD} ${YW}Creating:${CL} ${GN}${APP} LXC is ready${CL}"
  echo -e "${INFO}${YW} Method:${CL} ${BL}${METHOD}${CL}"
  echo -e "${INFO}${YW} CTID:${CL} ${BL}${CT_ID}${CL}"
  echo -e "${INFO}${YW} Hostname:${CL} ${BL}${HN}${CL}"
  echo -e "${INFO}${YW} Root password:${CL} ${BL}${PW_DISPLAY}${CL}"
  echo -e "${INFO}${YW} Network:${CL} ${BL}${NET}${GATE#,}${CL}"
  echo -e " ${HOLD} ${DGN}Access URL:${CL} ${BGN}http://${ip}:${APP_PORT}${CL}\n"
}

update_inside_container() {
  header_info
  if [[ ! -d /opt/wru ]]; then
    msg_error "No ${APP} installation found in this container"
    exit 1
  fi

  if [[ -t 0 ]] && command -v whiptail >/dev/null 2>&1; then
    local choice
    choice=$(whiptail --backtitle "Proxmox VE Helper Scripts" \
      --title "${APP} LXC Update" \
      --menu "Support/Update functions for ${APP} LXC. Choose an option:" \
      12 60 3 \
      "1" "YES (Silent Mode)" \
      "2" "YES (Verbose Mode)" \
      "3" "NO (Cancel Update)" \
      --nocancel --default-item "1" 3>&1 1>&2 2>&3)
    case "$choice" in
    3) exit_script ;;
    2) VERBOSE="yes" ;;
    *) VERBOSE="no" ;;
    esac
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
  if [[ -f /opt/wru/scripts/wru-update.sh ]]; then
    install -m 755 /opt/wru/scripts/wru-update.sh /usr/local/sbin/wru-update 2>/dev/null || true
    cat >/etc/sudoers.d/wru-update <<'EOF' 2>/dev/null || true
wru ALL=(root) NOPASSWD: /usr/local/sbin/wru-update
wru ALL=(root) NOPASSWD: /usr/bin/systemd-run
wru ALL=(root) NOPASSWD: /bin/systemctl reset-failed wru-online-update.service
EOF
    chmod 440 /etc/sudoers.d/wru-update 2>/dev/null || true
  fi
  local ip
  ip="$(hostname -I | awk '{print $1}')"
  echo -e "${INFO} Access URL: ${BGN}http://${ip}:${APP_PORT}${CL}"
  echo -e "${INFO} In-app updater: ${BGN}http://${ip}:${APP_PORT}/system${CL}"
  echo -e "${INFO} CLI: ${BL}sudo wru-update${CL}\n"
  exit 0
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

create_lxc_flow() {
  ensure_root
  header_info
  install_menu
  if [[ "$METHOD" == "update" ]]; then
    update_existing_ct
  else
    create_and_install
  fi
}

main() {
  if [[ -d /opt/wru ]] && ! is_proxmox_host; then
    update_inside_container
  elif is_proxmox_host; then
    create_lxc_flow
  else
    install_bare_metal
  fi
}

main "$@"
