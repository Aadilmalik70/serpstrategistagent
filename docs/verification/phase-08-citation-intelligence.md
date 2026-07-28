# Phase 8 — AI citation intelligence foundation

This slice adds a provider-safe foundation for measuring how AI answers mention a brand and cite sources.

## Delivered

- durable prompt sets scoped to a workspace and site;
- durable scan records with provider identity and persisted schedule metadata;
- normalized provider-result ingestion with bounded answer excerpts;
- brand mention, cited-source, and competitor-mention evidence;
- visibility, mention-rate, citation-rate, and competitor metrics;
- idempotent citation-gap records;
- governed simulation-only `citation_gap` actions;
- an operator-console **AI Citations** tab;
- migration `024` and API version `0.20.0`.

## Provider boundary

The first slice does not scrape ChatGPT, Google AI Overviews, Perplexity, or other consumer interfaces. It accepts results from an official/provider adapter or the manual test adapter. Provider-specific authentication, rate limits, answer/citation normalization, and scheduled workers remain separate follow-up work.

No citation recommendation can mutate a CMS, GitHub repository, or published page. Every gap action targets the existing simulation adapter and remains reviewable in the Action Queue.

## Manual API verification

After migration `024` is applied and the API is running:

1. Create a prompt set:

```http
POST /sites/{site_id}/citation-intelligence/prompt-sets
Authorization: Bearer ...
Content-Type: application/json

{
  "name": "Default AI visibility prompts",
  "brand_terms": ["SERP Strategists"],
  "competitor_terms": ["Ahrefs", "Semrush"],
  "prompts": ["What are the best AI SEO tools?"],
  "providers": ["manual"]
}
```

2. Start a scan with the returned `prompt_set_id`.
3. Ingest a result using the exact prompt from the prompt set:

```json
{
  "provider": "manual",
  "prompt": "What are the best AI SEO tools?",
  "answer": "SERP Strategists is useful for governed SEO operations. Ahrefs is another option.",
  "cited_urls": ["https://serpstrategists.com/"]
}
```

4. Finalize the scan.
5. Confirm the dashboard reports mention/citation rates and that a missing brand mention or citation creates a simulation-only action.

## Negative checks

- unsupported providers are rejected;
- prompts outside the selected prompt set are rejected;
- malformed citation URLs are discarded from evidence;
- a second ingestion for the same provider and prompt updates the existing result;
- no provider response stores more than the bounded answer excerpt;
- no GitHub, WordPress, or CMS mutation is attempted;
- workspace and site isolation is enforced on every endpoint.
