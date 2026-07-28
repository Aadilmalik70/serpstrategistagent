# Phase 7 — content intelligence

This slice adds a governed, deterministic content-intelligence loop on top of the first-party crawl and Search Console data.

## Delivered

- content_insights stores per-page freshness, decay, information-gain, topic, entity, and evidence signals.
- Decay compares two finalized 28-day Search Console windows and records clicks/impressions deltas.
- Information gain is explicitly labeled a deterministic lexical/query-uniqueness proxy; it does not claim semantic completeness.
- The semantic graph exposes page nodes, topic nodes, coverage edges, related-page edges, and topic clusters.
- Orphan pages are identified from the crawler's rebuilt linked_from metadata.
- internal_link_recommendations stores source/target evidence with stable site-scoped keys and resolution state.
- Refresh and internal-link recommendations become simulation-only governed draft actions. No CMS mutation is enabled by this phase.
- Operator console tab: Content Intelligence.

## API

- GET /sites/{site_id}/content-intelligence
- POST /sites/{site_id}/content-intelligence/analyze
- GET /sites/{site_id}/semantic-graph
- GET /sites/{site_id}/internal-link-recommendations

The authenticated workspace context scopes every request by workspace and site.

## Verification

1. Apply Alembic migration 023.
2. Crawl a site and run a Search Console sync if GSC is connected.
3. Open the site's Content Intelligence tab.
4. Select Analyze content.
5. Confirm decay evidence includes current/previous windows, link recommendations show source/target paths, and the action queue contains only simulation recommendations.
6. Re-run analysis and confirm stable insight/recommendation counts and no duplicate actions.

## Safety boundary

The phase produces evidence-backed plans and draft actions. It does not write to GitHub, WordPress, or another CMS. Any future mutation must pass the existing approval, snapshot, validation, and rollback lifecycle.
