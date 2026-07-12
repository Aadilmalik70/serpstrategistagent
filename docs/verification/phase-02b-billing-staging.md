# Phase 2B Railway and Stripe staging verification

## Preconditions

PR #5 must be deployed from `phase/02-billing-entitlements` with backend migration `008` applied.

Required Railway backend variables:

```env
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_GROWTH_PRICE_ID=price_...
STRIPE_SCALE_PRICE_ID=price_...
```

Keep all four values on the backend service only. Do not add them to the web service or any `NEXT_PUBLIC_` variable.

After adding or changing Railway variables, deploy the staged variable changes so the running service receives them.

## Stripe test-mode setup

1. Create recurring monthly Growth and Scale prices in Stripe test mode.
2. Copy each Price ID into the matching Railway variable.
3. In Stripe Workbench → Webhooks, create an event destination for:

   `https://serpstrategistagent-production.up.railway.app/billing/webhook`

4. Subscribe the destination to these snapshot events:

   - `checkout.session.completed`
   - `customer.subscription.created`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
   - `invoice.paid`
   - `invoice.payment_failed`

5. Copy the endpoint signing secret into `STRIPE_WEBHOOK_SECRET` and redeploy the backend.

The endpoint reads the raw request body, validates the `Stripe-Signature` timestamp and `v1` HMAC, and stores each Stripe event ID before applying subscription changes.

## Health and migration checks

```powershell
$API_URL = "https://serpstrategistagent-production.up.railway.app"
$WEB_URL = "https://web-production-53a7a.up.railway.app"

curl.exe "$API_URL/health"
curl.exe "$API_URL/ready"
curl.exe "$WEB_URL/api/health"
```

Expected backend version after deployment: `0.5.0`.

## Billing UI verification

1. Sign in to the deployed frontend.
2. Open `/settings`.
3. Confirm the **Billing & usage** card displays the current plan.
4. Open `/settings/billing`.
5. Confirm:
   - Audit, Growth, and Scale plans are visible.
   - current-period AI, token, SERP, and crawl usage is visible.
   - Stripe configuration warning is absent.
   - Growth and Scale buttons are enabled.

## Checkout verification

1. Select **Choose Growth**.
2. Confirm the browser is redirected to Stripe-hosted Checkout.
3. Complete payment with a Stripe test card.
4. Confirm Stripe redirects to:

   `/settings/billing?checkout=success`

5. Refresh the billing page.
6. Confirm:
   - plan is `growth`
   - status is `active`
   - Growth limits are displayed
   - **Manage subscription** is available

Repeat separately for Scale when needed.

## Billing portal verification

1. Click **Manage subscription**.
2. Confirm the browser opens the Stripe-hosted customer portal.
3. Test cancellation at period end.
4. Return to the application and verify `cancel_at_period_end` is reflected after Stripe sends `customer.subscription.updated`.

## Webhook verification

In Stripe Workbench, open the webhook event destination and inspect Event deliveries.

Expected:

- delivery returns HTTP `200`
- duplicate delivery returns HTTP `200` without applying the state twice
- invalid signatures return HTTP `400`
- no Stripe secret or authorization header appears in the response or Railway logs

## Quota verification

### Audit sites

1. Use an Audit workspace.
2. Create one site successfully.
3. Attempt to create a second site.
4. Expected response: HTTP `402` with code `quota_exceeded` and metric `sites`.

### Audit collaborators

1. Invite one collaborator successfully.
2. Attempt a second active/pending collaborator invitation.
3. Expected response: HTTP `402` with metric `team_members`.

### Crawls

Run a crawl and refresh `/settings/billing` after completion. The crawl-page counter should increase by the actual pages stored. A crawl is bounded by the remaining monthly allowance.

### AI and SerpAPI

Exercise a product workflow that calls the AI gateway and a workflow that performs a live SerpAPI query while supplying the request-scoped database session to the provider service.

Expected usage events:

- `ai_requests`
- `ai_tokens` when the upstream response supplies usage
- `serp_queries`

Each event must contain workspace, optional site, purpose, billing period, quantity, and safe non-secret details.

## Database verification

```sql
SELECT plan, status, stripe_customer_id, stripe_subscription_id,
       current_period_start, current_period_end, cancel_at_period_end
FROM subscriptions;

SELECT workspace_id, metric, quantity, period_start, period_end
FROM usage_counters
ORDER BY updated_at DESC;

SELECT workspace_id, site_id, metric, quantity, purpose, details, created_at
FROM usage_events
ORDER BY created_at DESC
LIMIT 50;

SELECT stripe_event_id, event_type, status, error, processed_at
FROM stripe_webhook_events
ORDER BY processed_at DESC
LIMIT 50;
```

No table should contain `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `AI_GATEWAY_API_KEY`, `SERPAPI_API_KEY`, or provider authorization headers.

## Acceptance

Phase 2B is accepted only after:

- test-mode Checkout succeeds
- signed webhook delivery succeeds
- duplicate webhook delivery is idempotent
- subscription state changes the workspace plan
- billing portal opens
- site, collaborator, crawl, AI, token, and SERP usage boundaries are verified
- secrets remain server-only
- CI and both Railway deployments are green
