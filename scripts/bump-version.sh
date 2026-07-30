#!/usr/bin/env bash
# Bump VERSION rev (0.1 → 0.2) before each push to main.
# FastAPI reads VERSION via app.version.version_string() — no main.py edit needed.
#
# Usage:
#   scripts/bump-version.sh          # bump only
#   scripts/bump-version.sh --tag    # bump, then create annotated git tag vN
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CUR="$(tr -d '[:space:]' <"$ROOT/VERSION" | sed 's/^v//')"
IFS='.' read -r -a parts <<<"$CUR"
last="${parts[-1]}"
if [[ "$last" =~ ^[0-9]+$ ]]; then
  parts[-1]="$((last + 1))"
else
  parts+=("1")
fi
NEW="$(IFS=.; echo "${parts[*]}")"
echo "$NEW" >"$ROOT/VERSION"
echo "Bumped version: v${CUR} → v${NEW}"
if [[ "${1:-}" == "--tag" ]]; then
  git -C "$ROOT" add VERSION
  git -C "$ROOT" tag -a "v${NEW}" -m "WRU v${NEW}"
  echo "Created tag v${NEW} (commit VERSION separately if needed)"
fi
