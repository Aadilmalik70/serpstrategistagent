"use client";

import { useState } from "react";
import useSWR from "swr";

import { apiFetch, OperatorApiError } from "@/lib/api";

type Insight = {
  page_id: string;
  path: string;
  title: string | null;
  content_age_days: number;
  freshness_score: number;
  decay_score: number;
  information_gain_score: number;
  topics: string[];
  entities: string[];
  metrics: {
    current?: { clicks?: number; impressions?: number; position?: number };
    previous?: { clicks?: number; impressions?: number; position?: number };
    click_delta?: number | null;
    impression_delta?: number | null;
  };
};

type Recommendation = {
  source_path: string;
  target_path: string;
  target_title: string | null;
  anchor_text: string;
  priority_score: number;
  confidence_score: number;
  reason: string;
};

type ContentIntelligence = {
  analyzed_at: string;
  period_end: string;
  total_pages: number;
  decaying_pages: number;
  orphan_pages: number;
  insights: Insight[];
  recommendations: Recommendation[];
  semantic_graph: {
    nodes: Array<{ type: string }>;
    edges: Array<{ type: string }>;
    topic_clusters: Array<{ topic: string; count: number; paths: string[] }>;
  };
  action_ids: string[];
};

export default function ContentIntelligencePanel({ siteId }: { siteId: string }) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const { data, error, mutate } = useSWR<ContentIntelligence>(
    `/sites/${siteId}/content-intelligence`,
    apiFetch,
  );

  async function analyze() {
    setBusy(true);
    setMessage("");
    try {
      const next = await apiFetch<ContentIntelligence>(
        `/sites/${siteId}/content-intelligence/analyze`,
        { method: "POST" },
      );
      await mutate(next, { revalidate: false });
      setMessage(
        `Analyzed ${next.total_pages} pages, found ${next.decaying_pages} decay signals and ${next.recommendations.length} link recommendations.`,
      );
    } catch (requestError) {
      setMessage(
        requestError instanceof OperatorApiError
          ? requestError.message
          : "Content intelligence analysis could not be completed.",
      );
    } finally {
      setBusy(false);
    }
  }

  if (error) {
    return (
      <div className="site-panel-error">
        Content intelligence is unavailable. Run a crawl first, then retry.
      </div>
    );
  }

  if (!data) {
    return <div className="site-panel-loading" />;
  }

  const decaying = [...data.insights]
    .filter((item) => item.decay_score > 0)
    .sort((left, right) => right.decay_score - left.decay_score)
    .slice(0, 8);

  return (
    <div className="site-feature-panel space-y-5">
      <section className="site-panel-hero">
        <div className="panel-hero-copy">
          <div>
            <p className="section-eyebrow">
              Phase 7 · Content intelligence
            </p>
            <h3 className="panel-title">
              Find what needs to improve next
            </h3>
            <p className="panel-description">
              Decay is measured against two finalized 28-day Search Console windows.
              Information gain is a deterministic lexical and query-uniqueness proxy,
              so every signal remains inspectable.
            </p>
          </div>
          <div className="panel-hero-actions"><span className="panel-status"><span className="site-ready-dot" /> Deterministic analysis</span><button type="button" onClick={analyze} disabled={busy} className="button button-primary">{busy ? "Analyzing…" : "Analyze content"}<span aria-hidden="true">↗</span></button></div>
        </div>
        {message && <p className="panel-feedback">{message}</p>}
      </section>

      <section className="insight-stat-grid">
        {[
          ["Pages analyzed", data.total_pages],
          ["Decay signals", data.decaying_pages],
          ["Orphan pages", data.orphan_pages],
          ["Graph nodes", data.semantic_graph.nodes.length],
          ["Draft actions", data.action_ids.length],
        ].map(([label, value]) => (
          <div key={label} className="insight-stat-card">
            <p>{label}</p>
            <strong>{value}</strong>
          </div>
        ))}
      </section>

      <section className="insight-columns">
        <div className="site-panel-card">
          <div className="panel-section-header"><div><h4>Decay and refresh queue</h4><p>Pages showing a measurable drop across finalized windows.</p></div><span className="panel-count panel-count-red">{decaying.length}</span></div>
          <div className="panel-list">
            {decaying.length === 0 && (
              <p className="panel-empty">No decay threshold crossed in the latest windows.</p>
            )}
            {decaying.map((item) => (
              <div key={item.page_id} className="panel-list-row">
                <div className="panel-list-main"><p>{item.path}</p><small>{item.title || "Untitled"}</small></div>
                <span className="panel-score panel-score-red">{item.decay_score}</span>
                <div className="panel-list-note">
                  <span>Information gain {item.information_gain_score}</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="site-panel-card">
          <div className="panel-section-header"><div><h4>Internal-link recommendations</h4><p>Evidence-backed paths to strengthen topical coverage.</p></div><span className="panel-count">{data.recommendations.length}</span></div>
          <div className="panel-list">
            {data.recommendations.slice(0, 8).map((item) => (
              <div key={`${item.source_path}-${item.target_path}`} className="panel-list-row panel-link-row">
                <div className="panel-link-route"><span>{item.source_path}</span><b>→</b><span>{item.target_path}</span></div>
                <small>Anchor “{item.anchor_text}” · priority {item.priority_score} · confidence {item.confidence_score}</small>
              </div>
            ))}
            {data.recommendations.length === 0 && (
              <p className="panel-empty">No evidence-backed orphan links found.</p>
            )}
          </div>
        </div>
      </section>

      <section className="site-panel-card">
        <div className="panel-section-header"><div><h4>Topic clusters</h4><p>Recurring themes found across the crawled pages.</p></div><span className="panel-count">{data.semantic_graph.topic_clusters.length}</span></div>
        <div className="topic-cluster-list">
          {data.semantic_graph.topic_clusters.slice(0, 24).map((cluster) => (
            <span
              key={cluster.topic}
              className="topic-chip"
            >
              {cluster.topic}<b>{cluster.count}</b>
            </span>
          ))}
          {data.semantic_graph.topic_clusters.length === 0 && (
            <p className="panel-empty">Run a crawl with page titles and headings to build clusters.</p>
          )}
        </div>
      </section>
    </div>
  );
}
