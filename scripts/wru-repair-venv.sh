#!/usr/bin/env bash
# Recreate the WRU Python environment in /opt/wru (never move a venv).
# Fixes "No module named sqlalchemy" after a broken update.
#
# As root on the WRU CT:
#   sudo bash /opt/wru/scripts/wru-repair-venv.sh
#   sudo wru-repair-venv
set -euo pipefail

APP_DIR="${WRU_APP_DIR:-/opt/wru}"
REQ="${APP_DIR}/requirements.txt"
VENV="${APP_DIR}/.venv"
VENV_PY="${VENV}/bin/python"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Must run as root: sudo bash $0" >&2
  exit 1
fi

if [[ ! -f "${APP_DIR}/app/main.py" ]]; then
  echo "WRU code is missing at ${APP_DIR}. Clone it first, then re-run." >&2
  exit 1
fi

echo "=== WRU venv repair $(date -Is) ==="
echo "App: ${APP_DIR}"

if [[ -z "${WRU_REPAIR_FORCE:-}" && -x "$VENV_PY" ]] \
  && "$VENV_PY" -c "import sqlalchemy, fastapi, uvicorn" >/dev/null 2>&1; then
  echo "Python packages already import (sqlalchemy/fastapi/uvicorn)."
  systemctl start postgresql 2>/dev/null || true
  systemctl start wru 2>/dev/null || true
  echo "=== venv repair skipped (healthy) ==="
  exit 0
fi

export DEBIAN_FRONTEND=noninteractive
apt-get install -y python3 python3-venv python3-pip python3-full >/dev/null 2>&1 || true

systemctl stop wru 2>/dev/null || true
systemctl start postgresql 2>/dev/null || true

rm -rf "$VENV"
if ! python3 -m venv "$VENV"; then
  apt-get install -y python3-venv python3-full python3-pip
  python3 -m venv "$VENV"
fi

if [[ ! -x "$VENV_PY" ]]; then
  echo "venv python was not created at ${VENV_PY}" >&2
  exit 1
fi

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

"$VENV_PY" -m pip install --upgrade pip
if ! "$VENV_PY" -m pip install -r "$REQ"; then
  echo "Bulk pip failed — installing core packages individually"
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" || "$line" == \#* ]] && continue
    "$VENV_PY" -m pip install "$line" || true
  done < "$REQ"
fi
"$VENV_PY" -m pip install "pillow==11.1.0" || echo "Pillow skipped (optional)"

if ! "$VENV_PY" -c "import sqlalchemy, fastapi, uvicorn"; then
  echo "Packages still missing after pip install." >&2
  "$VENV_PY" -m pip install sqlalchemy fastapi "uvicorn[standard]" psycopg2-binary
fi
"$VENV_PY" -c "import sqlalchemy, fastapi, uvicorn; print('packages ok:', sqlalchemy.__version__)"

if [[ -f /etc/default/wru ]]; then
  set -a
  # shellcheck disable=SC1091
  source /etc/default/wru
  set +a
fi
(
  cd "$APP_DIR"
  "$VENV_PY" -c "from app.migrate import run_migrations; run_migrations()" \
    || echo "Migration warning — starting anyway"
)

if id -u wru >/dev/null 2>&1; then
  chown -R wru:wru "$APP_DIR" || true
fi

systemctl daemon-reload 2>/dev/null || true
systemctl start wru 2>/dev/null || true
sleep 2
if command -v curl >/dev/null 2>&1; then
  curl -fsS --connect-timeout 3 "http://127.0.0.1:${WRU_PORT:-8000}/health" || true
  echo
fi
echo "=== venv repair complete ==="
echo "Check: systemctl status wru"
echo "Then:  curl -sS http://127.0.0.1:${WRU_PORT:-8000}/health"
