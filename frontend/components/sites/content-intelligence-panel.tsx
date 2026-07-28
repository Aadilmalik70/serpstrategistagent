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
      <div className="rounded-[20px] border border-red-200 bg-red-50 p-6 text-sm text-red-700">
        Content intelligence is unavailable. Run a crawl first, then retry.
      </div>
    );
  }

  if (!data) {
    return <div className="h-64 animate-pulse rounded-[20px] bg-gray-200" />;
  }

  const decaying = [...data.insights]
    .filter((item) => item.decay_score > 0)
    .sort((left, right) => right.decay_score - left.decay_score)
    .slice(0, 8);

  return (
    <div className="space-y-5">
      <section className="rounded-[20px] border border-gray-200 bg-white p-5 sm:p-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-gray-500">
              Phase 7 · Content intelligence
            </p>
            <h3 className="mt-2 text-2xl font-semibold tracking-[-0.035em]">
              Find what needs to improve next
            </h3>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-gray-600">
              Decay is measured against two finalized 28-day Search Console windows.
              Information gain is a deterministic lexical and query-uniqueness proxy,
              so every signal remains inspectable.
            </p>
          </div>
          <button
            type="button"
            onClick={analyze}
            disabled={busy}
            className="min-h-11 rounded-full bg-[#202020] px-5 text-sm font-semibold text-white disabled:opacity-50"
          >
            {busy ? "Analyzing…" : "Analyze content"}
          </button>
        </div>
        {message && <p className="mt-4 text-sm text-gray-700">{message}</p>}
      </section>

      <section className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        {[
          ["Pages", data.total_pages],
          ["Decaying", data.decaying_pages],
          ["Orphans", data.orphan_pages],
          ["Graph nodes", data.semantic_graph.nodes.length],
          ["Draft actions", data.action_ids.length],
        ].map(([label, value]) => (
          <div key={label} className="rounded-2xl border border-gray-200 bg-white p-4">
            <p className="text-xs text-gray-500">{label}</p>
            <p className="mt-2 text-2xl font-semibold text-gray-950">{value}</p>
          </div>
        ))}
      </section>

      <section className="grid gap-5 lg:grid-cols-2">
        <div className="rounded-[20px] border border-gray-200 bg-white p-5">
          <h4 className="text-lg font-semibold">Decay and refresh queue</h4>
          <div className="mt-4 divide-y divide-gray-100">
            {decaying.length === 0 && (
              <p className="py-4 text-sm text-gray-500">No decay threshold crossed in the latest windows.</p>
            )}
            {decaying.map((item) => (
              <div key={item.page_id} className="py-3">
                <div className="flex items-center justify-between gap-3">
                  <p className="truncate text-sm font-medium text-gray-950">{item.path}</p>
                  <span className="rounded-full bg-red-50 px-2 py-1 text-xs font-semibold text-red-700">
                    {item.decay_score}
                  </span>
                </div>
                <p className="mt-1 text-xs text-gray-500">
                  {item.title || "Untitled"} · information gain {item.information_gain_score}
                </p>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-[20px] border border-gray-200 bg-white p-5">
          <h4 className="text-lg font-semibold">Internal-link recommendations</h4>
          <div className="mt-4 divide-y divide-gray-100">
            {data.recommendations.slice(0, 8).map((item) => (
              <div key={`${item.source_path}-${item.target_path}`} className="py-3">
                <p className="text-sm font-medium text-gray-950">
                  {item.source_path} → {item.target_path}
                </p>
                <p className="mt-1 text-xs text-gray-500">
                  Anchor “{item.anchor_text}” · priority {item.priority_score} · confidence {item.confidence_score}
                </p>
              </div>
            ))}
            {data.recommendations.length === 0 && (
              <p className="py-4 text-sm text-gray-500">No evidence-backed orphan links found.</p>
            )}
          </div>
        </div>
      </section>

      <section className="rounded-[20px] border border-gray-200 bg-white p-5">
        <h4 className="text-lg font-semibold">Topic clusters</h4>
        <div className="mt-4 flex flex-wrap gap-2">
          {data.semantic_graph.topic_clusters.slice(0, 24).map((cluster) => (
            <span
              key={cluster.topic}
              className="rounded-full border border-gray-200 bg-gray-50 px-3 py-1.5 text-xs text-gray-700"
            >
              {cluster.topic} · {cluster.count}
            </span>
          ))}
          {data.semantic_graph.topic_clusters.length === 0 && (
            <p className="text-sm text-gray-500">Run a crawl with page titles and headings to build clusters.</p>
          )}
        </div>
      </section>
    </div>
  );
}
