#!/usr/bin/env bash
set -euo pipefail

for cmd in npx uvx copilot; do
  if command -v "$cmd" >/dev/null 2>&1; then
    echo "[ok] $cmd: $(command -v "$cmd")"
  else
    echo "[missing] $cmd"
  fi
done