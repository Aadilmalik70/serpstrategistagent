# Phase 2 Slice 6 — Platform-managed AI and SERP providers

## Scope

SERP Strategists centrally manages shared AI inference and live SERP collection. Workspace members do not supply OpenAI, Gemini, SerpAPI, Serper, or AI-gateway keys.

Customer-owned integration storage remains limited to property-specific connections such as WordPress. GSC and GA4 remain OAuth integrations, and production GitHub access will use a GitHub App.

## Railway configuration

Configure these secrets on the backend service:

- `AI_GATEWAY_API_KEY`
- `SERPAPI_API_KEY`

The following non-secret defaults are included in application configuration and may be overridden in Railway:

- `AI_GATEWAY_BASE_URL=https://api.17.wtf/v1`
- `AI_PRIMARY_MODEL=posiden/deepseek-v4-flash`
- `AI_REASONING_MODEL=zeus/claude-sonnet-4-6`
- `AI_FALLBACK_MODEL=latina/gpt-5.6-terra`
- `AI_SECONDARY_FALLBACK_MODEL=latina/gpt-5.6-luna`
- `SERPAPI_BASE_URL=https://serpapi.com/search.json`

## Implemented controls

- Manual workspace credentials for platform-managed providers are rejected.
- The integrations catalog does not expose platform-managed providers.
- The AI gateway supports chat-completions, Anthropic messages, and Responses request contracts.
- Model fallback is configuration-driven.
- SerpAPI requests use only the backend Railway secret.
- AI and SERP calls carry workspace, optional site, and purpose attribution for future metering.
- Provider authentication failures, rate limits, timeouts, upstream failures, and malformed JSON are normalized without returning secret values.

## Automated verification

CI verifies:

- backend compilation and migrations
- integration lifecycle and tenant isolation
- rejection of customer BYOK for platform-managed providers
- all three AI-gateway request contracts
- model fallback after rate limiting
- server-managed SerpAPI authentication and attribution
- frontend lint, typecheck, and production build

## Staging smoke test

After fresh secrets are configured in Railway:

1. Call the AI gateway through a server-side code path and verify the configured primary model responds.
2. Temporarily simulate or observe a retryable primary-model failure and verify fallback routing.
3. Run one SerpAPI query and verify a successful live result.
4. Confirm neither secret appears in browser traffic, API responses, application logs, traces, sessions, integration metadata, or database records.
5. Rotate any credential that was previously pasted into chat or another non-secret channel before use.
