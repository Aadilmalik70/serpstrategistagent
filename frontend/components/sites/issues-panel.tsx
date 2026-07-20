"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import useSWR from "swr";

import { apiFetch } from "@/lib/api";


type Finding = {
  id: string;
  finding_type: string;
  detector_version: string;
  category: string;
  severity: string;
  status: string;
  title: string;
  description: string;
  recommendation: string | null;
  affected_url: string | null;
  affected_urls: string[];
  evidence: Record<string, unknown>[];
  impact_score: number;
  confidence_score: number;
  effort_score: number;
  occurrence_count: number;
  regression_count: number;
  first_seen_at: string;
  last_seen_at: string;
  action_id: string | null;
  action_status: string | null;
  action_adapter: string | null;
  patch_status: string | null;
  patch_reason: string | null;
  patch_source_path: string | null;
};

type FindingQueue = {
  items: Finding[];
  total: number;
  counts_by_status: Record<string, number>;
  counts_by_severity: Record<string, number>;
};

type RefreshResult = {
  created: number;
  updated: number;
  regressed: number;
  resolved: number;
  active: number;
  actions_created: number;
};

interface SiteInfo {
  domain?: string;
}

const severityStyles: Record<string, string> = {
  critical: "border-red-200 bg-red-50 text-red-800",
  high: "border-orange-200 bg-orange-50 text-orange-800",
  medium: "border-amber-200 bg-amber-50 text-amber-800",
  low: "border-blue-200 bg-blue-50 text-blue-800",
};

const statusStyles: Record<string, string> = {
  open: "bg-slate-100 text-slate-700",
  regressed: "bg-fuchsia-100 text-fuchsia-800",
  resolved: "bg-emerald-100 text-emerald-800",
  dismissed: "bg-gray-100 text-gray-500",
};

export default function IssuesPanel({ siteId, site }: { siteId: string; site?: SiteInfo }) {
  const [status, setStatus] = useState("active");
  const [severity, setSeverity] = useState("all");
  const [refreshing, setRefreshing] = useState(false);
  const [refreshResult, setRefreshResult] = useState<RefreshResult | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const query = `/technical-findings/sites/${siteId}?status=${status}&limit=500`;
  const { data, error, mutate } = useSWR<FindingQueue>(query, (path: string) => apiFetch<FindingQueue>(path));

  const findings = useMemo(() => {
    const items = data?.items ?? [];
    return severity === "all" ? items : items.filter((item) => item.severity === severity);
  }, [data, severity]);

  async function refreshFindings() {
    setRefreshing(true);
    setErrorMessage(null);
    try {
      const result = await apiFetch<RefreshResult>(`/technical-findings/sites/${siteId}/refresh`, {
        method: "POST",
      });
      setRefreshResult(result);
      await mutate();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Technical analysis failed.");
    } finally {
      setRefreshing(false);
    }
  }

  async function updateStatus(findingId: string, nextStatus: "open" | "dismissed") {
    await apiFetch(`/technical-findings/${findingId}`, {
      method: "PATCH",
      body: JSON.stringify({ status: nextStatus }),
    });
    await mutate();
  }

  async function ensureAction(findingId: string) {
    setErrorMessage(null);
    try {
      await apiFetch(`/technical-findings/${findingId}/action`, { method: "POST" });
      await mutate();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Action creation failed.");
    }
  }

  if (error) {
    return <p className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">Unable to load technical findings.</p>;
  }
  if (!data) {
    return <div className="h-48 animate-pulse rounded-xl bg-gray-100" />;
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h3 className="text-lg font-semibold text-gray-950">Technical Findings</h3>
          <p className="mt-1 text-sm text-gray-500">
            Stable, crawl-backed findings for {site?.domain || "this site"}. Repeated scans update the same finding.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link href={`/actions?site_id=${siteId}`} className="rounded-md border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">
            Open action queue
          </Link>
          <button
            type="button"
            onClick={refreshFindings}
            disabled={refreshing}
            className="rounded-md bg-gray-950 px-4 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {refreshing ? "Analyzing…" : "Refresh findings"}
          </button>
        </div>
      </div>

      {refreshResult && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          {refreshResult.active} active · {refreshResult.created} new · {refreshResult.resolved} resolved · {refreshResult.regressed} regressed · {refreshResult.actions_created} actions created
        </div>
      )}
      {errorMessage && <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{errorMessage}</div>}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {(["critical", "high", "medium", "low"] as const).map((level) => (
          <button
            type="button"
            key={level}
            onClick={() => setSeverity(severity === level ? "all" : level)}
            className={`rounded-lg border p-3 text-left ${severityStyles[level]} ${severity === level ? "ring-2 ring-gray-900 ring-offset-1" : ""}`}
          >
            <span className="block text-xs font-semibold uppercase">{level}</span>
            <span className="mt-1 block text-2xl font-semibold">{data.counts_by_severity[level] ?? 0}</span>
          </button>
        ))}
      </div>

      <div className="flex flex-wrap gap-2">
        {[
          ["active", "Active"],
          ["regressed", "Regressed"],
          ["resolved", "Resolved"],
          ["dismissed", "Dismissed"],
          ["all", "All"],
        ].map(([value, label]) => (
          <button
            type="button"
            key={value}
            onClick={() => setStatus(value)}
            className={`rounded-full px-3 py-1.5 text-xs font-medium ${status === value ? "bg-gray-950 text-white" : "border border-gray-300 bg-white text-gray-600"}`}
          >
            {label}{value !== "active" && value !== "all" ? ` (${data.counts_by_status[value] ?? 0})` : ""}
          </button>
        ))}
      </div>

      {findings.length === 0 ? (
        <div className="rounded-xl border border-dashed border-gray-300 py-14 text-center">
          <p className="font-medium text-gray-800">No findings in this view</p>
          <p className="mt-1 text-sm text-gray-500">Run a successful crawl, then refresh the deterministic analysis.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {findings.map((finding) => (
            <article key={finding.id} className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${severityStyles[finding.severity] || "border-gray-200 bg-gray-50 text-gray-700"}`}>
                      {finding.severity}
                    </span>
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${statusStyles[finding.status] || statusStyles.open}`}>
                      {finding.status}
                    </span>
                    <span className="font-mono text-xs text-gray-400">{finding.finding_type}</span>
                  </div>
                  <h4 className="mt-2 font-semibold text-gray-950">{finding.title}</h4>
                  <p className="mt-1 text-sm text-gray-600">{finding.description}</p>
                </div>
                <div className="grid grid-cols-3 gap-1 text-center text-xs">
                  <Score label="Impact" value={finding.impact_score} />
                  <Score label="Confidence" value={finding.confidence_score} />
                  <Score label="Effort" value={finding.effort_score} />
                </div>
              </div>

              {finding.affected_urls.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {finding.affected_urls.slice(0, 8).map((url) => (
                    <span key={url} className="max-w-full truncate rounded bg-gray-100 px-2 py-1 font-mono text-xs text-gray-600">{url}</span>
                  ))}
                  {finding.affected_urls.length > 8 && <span className="px-2 py-1 text-xs text-gray-400">+{finding.affected_urls.length - 8} more</span>}
                </div>
              )}

              {finding.recommendation && (
                <p className="mt-3 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{finding.recommendation}</p>
              )}

              {finding.action_id && (
                <div className={`mt-3 rounded-lg border px-3 py-2 text-sm ${finding.action_adapter === "github" ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-gray-200 bg-gray-50 text-gray-600"}`}>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold">
                      {finding.action_adapter === "github" ? "GitHub patch ready" : "Simulation fallback"}
                    </span>
                    {finding.patch_source_path && <span className="rounded bg-white/70 px-2 py-0.5 font-mono text-xs">{finding.patch_source_path}</span>}
                  </div>
                  {finding.action_adapter !== "github" && finding.patch_reason && <p className="mt-1 text-xs">{finding.patch_reason}</p>}
                </div>
              )}

              <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-gray-100 pt-3">
                <p className="text-xs text-gray-400">
                  Seen {finding.occurrence_count}× · regressions {finding.regression_count} · detector {finding.detector_version}
                </p>
                <div className="flex gap-2">
                  {finding.action_id ? (
                    <Link href={`/actions/${finding.action_id}`} className="rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700">
                      {finding.action_adapter === "github" ? "Review GitHub patch" : "View action"} · {finding.action_status}
                    </Link>
                  ) : finding.status === "open" || finding.status === "regressed" ? (
                    <button type="button" onClick={() => ensureAction(finding.id)} className="rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700">
                      Create action
                    </button>
                  ) : null}
                  {finding.status === "dismissed" ? (
                    <button type="button" onClick={() => updateStatus(finding.id, "open")} className="rounded-md border border-gray-300 px-3 py-1.5 text-xs text-gray-600 hover:bg-gray-50">Reopen</button>
                  ) : finding.status === "open" || finding.status === "regressed" ? (
                    <button type="button" onClick={() => updateStatus(finding.id, "dismissed")} className="rounded-md border border-gray-300 px-3 py-1.5 text-xs text-gray-600 hover:bg-gray-50">Dismiss</button>
                  ) : null}
                </div>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}

function Score({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md bg-gray-50 px-2 py-1.5">
      <span className="block font-semibold text-gray-900">{value}</span>
      <span className="text-[10px] uppercase text-gray-400">{label}</span>
    </div>
  );
}
