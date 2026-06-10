#!/usr/bin/env bash
set -euo pipefail

payload="$(cat)"

if [ -z "$payload" ]; then
  printf '%s' '{}'
  exit 0
fi

if printf '%s' "$payload" | grep -E 'git push|rm -rf|Remove-Item' >/dev/null 2>&1; then
  printf '%s' '{"permissionDecision":"deny","permissionDecisionReason":"Denied by SEO Operator safe-fix policy."}'
else
  printf '%s' '{}'
fi