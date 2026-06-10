#!/usr/bin/env bash
set -euo pipefail

search_state="unknown"
search_detail="not checked"
ga4_state="unknown"
ga4_detail="not checked"
serp_state="unknown"
serp_detail="not checked"

if command -v npx >/dev/null 2>&1; then
  if accounts_raw="$(npx -y search-console-mcp accounts list 2>/dev/null || true)" && printf '%s' "$accounts_raw" | grep '"accounts"' >/dev/null 2>&1; then
    search_state="ready"
    search_detail="Search Console accounts are available."
  else
    search_state="auth-needed"
    search_detail="Search Console CLI responded without saved accounts."
  fi
else
  search_state="error"
  search_detail="npx is not available."
fi

if [ -z "${GOOGLE_APPLICATION_CREDENTIALS:-}" ]; then
  ga4_state="blocked"
  ga4_detail="GOOGLE_APPLICATION_CREDENTIALS is not set."
elif [ ! -f "${GOOGLE_APPLICATION_CREDENTIALS}" ]; then
  ga4_state="blocked"
  ga4_detail="Credential file path does not exist."
elif [ -z "${GOOGLE_PROJECT_ID:-${GOOGLE_CLOUD_PROJECT:-}}" ]; then
  ga4_state="blocked"
  ga4_detail="GOOGLE_PROJECT_ID is not set."
else
  ga4_state="configured"
  ga4_detail="Credential path and project env are present. API enablement still needs runtime confirmation."
fi

if [ -z "${SERPAPI_API_KEY:-}" ]; then
  serp_state="blocked"
  serp_detail="SERPAPI_API_KEY is not set."
else
  serp_state="configured"
  serp_detail="SERPAPI_API_KEY is present."
fi

cat <<EOF
{
  "searchConsoleSuite": {
    "state": "${search_state}",
    "detail": "${search_detail}"
  },
  "ga4Official": {
    "state": "${ga4_state}",
    "detail": "${ga4_detail}"
  },
  "serpapi": {
    "state": "${serp_state}",
    "detail": "${serp_detail}"
  }
}
EOF