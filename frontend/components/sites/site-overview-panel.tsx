"use client";

import Link from "next/link";
import type { CSSProperties } from "react";

type OverviewSite = {
  id: string;
  name: string;
  domain: string;
  status: string;
  page_count: number;
  issue_count: number;
  health_score: number | null;
  health_grade: string | null;
  updated_at: string;
  latest_run: {
    issues_found: number;
    pages_analyzed: number;
    summary: string | null;
    completed_at: string | null;
  } | null;
  librecrawl_enabled: boolean;
};

type OverviewTab = "issues" | "pages" | "content" | "citation" | "search" | "agent" | "serp-content";

function formatDate(value: string | null | undefined) {
  if (!value) return "Not run yet";
  return new Date(value).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

function scoreTone(score: number | null) {
  if (score === null) return "neutral";
  if (score >= 80) return "good";
  if (score >= 60) return "watch";
  return "urgent";
}

export default function SiteOverviewPanel({
  site,
  onNavigate,
}: {
  site: OverviewSite;
  onNavigate: (tab: OverviewTab) => void;
}) {
  const score = site.health_score;
  const tone = scoreTone(score);
  const issueCount = site.issue_count || site.latest_run?.issues_found || 0;

  return (
    <div className="site-overview space-y-5">
      <section className="overview-grid">
        <div className="overview-health-panel">
          <div className={`health-ring health-ring-${tone}`} style={{ "--ring-progress": `${score ?? 0}%` } as CSSProperties} aria-label={score === null ? "Health score not available" : `Health score ${score} out of 100`}>
            <div className="health-ring-inner">
              <strong>{score ?? "—"}</strong>
              {score !== null && <span>/100</span>}
            </div>
          </div>
          <div className="min-w-0">
            <p className="section-eyebrow">Site health · {site.health_grade || "Awaiting analysis"}</p>
            <h2 className="overview-title">Your next growth moves</h2>
            <p className="overview-copy">
              {score === null
                ? "Run the agent to turn your first crawl into a prioritized, evidence-backed plan."
                : "The site is crawlable and healthy. Focus the next pass on the few issues with the clearest search impact."}
            </p>
            <div className="priority-list">
              <button type="button" className="priority-row" onClick={() => onNavigate("issues")}>
                <span className="priority-icon priority-icon-orange">!</span>
                <span className="min-w-0 flex-1">
                  <strong>Review technical findings</strong>
                  <small>{issueCount ? `${issueCount} open finding${issueCount === 1 ? "" : "s"} to review` : "No open findings reported"}</small>
                </span>
                <span className="priority-arrow">→</span>
              </button>
              <button type="button" className="priority-row" onClick={() => onNavigate("content")}>
                <span className="priority-icon priority-icon-blue">↗</span>
                <span className="min-w-0 flex-1">
                  <strong>Find content opportunities</strong>
                  <small>Check decay, orphan pages, and internal links</small>
                </span>
                <span className="priority-arrow">→</span>
              </button>
            </div>
          </div>
        </div>

        <aside className="overview-activity-panel">
          <div className="activity-header">
            <div>
              <p className="section-eyebrow">Agent activity</p>
              <h2 className="activity-title">{site.status.replaceAll("_", " ") || "Ready"}</h2>
            </div>
            <span className="status-dot" aria-label="Ready" />
          </div>
          <p className="overview-copy">
            Review recommendations, approve safe actions, and keep a complete record of what changed.
          </p>
          <dl className="activity-meta">
            <div><dt>Last analysis</dt><dd>{formatDate(site.latest_run?.completed_at || site.updated_at)}</dd></div>
            <div><dt>Pages analyzed</dt><dd>{site.latest_run?.pages_analyzed || site.page_count}</dd></div>
            <div><dt>Crawler</dt><dd>{site.librecrawl_enabled ? "Enhanced crawl" : "First-party crawl"}</dd></div>
          </dl>
          <div className="activity-actions">
            <Link href={`/actions?site_id=${site.id}`} className="button button-primary button-wide">Open action queue <span>↗</span></Link>
            <button type="button" className="button button-secondary button-wide" onClick={() => onNavigate("agent")}>Ask the agent <span>→</span></button>
          </div>
        </aside>
      </section>

      <section>
        <div className="section-heading-row">
          <div><h2 className="section-title">What needs attention</h2><p className="section-subtitle">Choose a workstream to inspect the latest evidence.</p></div>
          <button type="button" className="text-action" onClick={() => onNavigate("issues")}>View all findings <span>→</span></button>
        </div>
        <div className="attention-grid">
          <button type="button" className="attention-card" onClick={() => onNavigate("issues")}>
            <span className="attention-icon attention-icon-red">!</span>
            <span className="attention-body"><strong>Technical findings</strong><small>{issueCount ? `${issueCount} open issue${issueCount === 1 ? "" : "s"} · prioritize by impact and effort` : "No active issues · run a refresh to confirm"}</small></span>
            <span className="attention-arrow">↗</span>
          </button>
          <button type="button" className="attention-card" onClick={() => onNavigate("content")}>
            <span className="attention-icon attention-icon-purple">✦</span>
            <span className="attention-body"><strong>Content Intelligence</strong><small>Detect decay, information gaps, orphans, and link opportunities</small></span>
            <span className="attention-arrow">↗</span>
          </button>
          <button type="button" className="attention-card" onClick={() => onNavigate("search")}>
            <span className="attention-icon attention-icon-green">⌁</span>
            <span className="attention-body"><strong>Search visibility</strong><small>Connect Search Console to uncover queries worth acting on</small></span>
            <span className="attention-arrow">↗</span>
          </button>
          <button type="button" className="attention-card" onClick={() => onNavigate("serp-content")}>
            <span className="attention-icon attention-icon-orange">✎</span>
            <span className="attention-body"><strong>SERP Content</strong><small>Turn search evidence into briefs, drafts, and governed publishing actions</small></span>
            <span className="attention-arrow">↗</span>
          </button>
        </div>
      </section>
    </div>
  );
}
