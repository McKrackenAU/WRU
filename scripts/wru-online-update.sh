#!/usr/bin/env bash
# Copyright (c) 2026 McKrackenAU / WRU
# Passwordless sudo entrypoint for in-app GitHub updates.
#
# Usage:
#   wru-online-update --check              # probe sudo / helper (no install)
#   wru-online-update [branch] [repo]      # run full update
#
# Called by the web UI via: sudo systemd-run --no-block … wru-online-update …
set -euo pipefail

UPDATE_BIN="/usr/local/sbin/wru-update"
DEFAULT_REPO="https://github.com/McKrackenAU/WRU.git"

if [[ "${1:-}" == "--check" ]]; then
  if [[ "$(id -u)" -ne 0 ]]; then
    echo "Must run as root (via sudo)." >&2
    exit 1
  fi
  if [[ ! -x "$UPDATE_BIN" && ! -x /usr/bin/wru-update ]]; then
    echo "Missing ${UPDATE_BIN}" >&2
    exit 3
  fi
  echo "ok"
  exit 0
fi

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Must run as root (via sudo)." >&2
  exit 1
fi

export WRU_BRANCH="${1:-${WRU_BRANCH:-main}}"
export WRU_REPO="${2:-${WRU_REPO:-$DEFAULT_REPO}}"

if [[ -x "$UPDATE_BIN" ]]; then
  exec "$UPDATE_BIN"
fi
if [[ -x /usr/bin/wru-update ]]; then
  exec /usr/bin/wru-update
fi

# Helper missing — still repair the site from GitHub.
exec bash -c "$(curl -fsSL --connect-timeout 15 --max-time 90 https://raw.githubusercontent.com/McKrackenAU/WRU/main/scripts/wru-update.sh)"
