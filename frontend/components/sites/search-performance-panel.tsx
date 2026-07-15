"use client";

import { useState } from "react";
import useSWR from "swr";

import { apiFetch, OperatorApiError } from "@/lib/api";

type Opportunity = {
  id: string;
  opportunity_type: string;
  status: string;
  title: string;
  query: string | null;
  page_url: string | null;
  priority_score: number;
  confidence_score: number;
  metrics: Record<string, unknown>;
  last_detected_at: string;
};

type OpportunityList = { items: Opportunity[]; total: number };

type InspectionResult = {
  id: string;
  inspection_url: string;
  verdict: string;
  coverage_state: string | null;
  robots_txt_state: string | null;
  indexing_state: string | null;
  page_fetch_state: string | null;
  google_canonical: string | null;
  user_canonical: string | null;
  inspected_at: string;
};

type InspectionResultList = { items: InspectionResult[]; total: number };

type SyncJob = {
  id: string;
  status: string;
  attempt_count: number;
  max_attempts: number;
  result: { rows?: number; processed?: number; total?: number; opportunities?: number } | null;
  error_message: string | null;
};

export default function SearchPerformancePanel({ siteId }: { siteId: string }) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [inspectionBusy, setInspectionBusy] = useState(false);
  const [inspectionMessage, setInspectionMessage] = useState("");
  const { data, error, mutate } = useSWR<OpportunityList>(
    `/integrations/google-data/opportunities/${siteId}`,
    apiFetch,
  );
  const { data: job, error: jobError, mutate: mutateJob } = useSWR<SyncJob | null>(
    `/integrations/google-data/search-sync/sites/${siteId}/latest`,
    apiFetch,
    {
      refreshInterval: (latest) =>
        latest && !["completed", "failed", "cancelled"].includes(latest.status)
          ? 3000
          : 0,
      onSuccess: (current) => {
        if (!current) return;
        if (current.status === "completed") {
          setBusy(false);
          setMessage(`Synced ${current.result?.rows ?? 0} Search Console rows and found ${current.result?.opportunities ?? 0} opportunities.`);
          void mutate();
        } else if (current.status === "failed") {
          setBusy(false);
          setMessage(current.error_message || "Search Console synchronization failed.");
        }
      },
    },
  );
  const { data: inspections, error: inspectionError, mutate: mutateInspections } =
    useSWR<InspectionResultList>(
      `/integrations/google-data/url-inspection/results/${siteId}`,
      apiFetch,
    );
  const {
    data: inspectionJob,
    error: inspectionJobError,
    mutate: mutateInspectionJob,
  } = useSWR<SyncJob | null>(
    `/integrations/google-data/url-inspection/sites/${siteId}/latest`,
    apiFetch,
    {
      refreshInterval: (latest) =>
        latest && !["completed", "failed", "cancelled"].includes(latest.status)
          ? 3000
          : 0,
      onSuccess: (current) => {
        if (!current) return;
        if (current.status === "completed") {
          setInspectionBusy(false);
          setInspectionMessage(
            `Inspected ${current.result?.processed ?? 0} URLs and found ${current.result?.opportunities ?? 0} indexation opportunities.`,
          );
          void mutateInspections();
          void mutate();
        } else if (current.status === "failed") {
          setInspectionBusy(false);
          setInspectionMessage(current.error_message || "URL Inspection failed.");
        }
      },
    },
  );

  async function startSync() {
    setBusy(true);
    setMessage("");
    try {
      const created = await apiFetch<SyncJob>(`/integrations/google-data/search-sync/${siteId}`, {
        method: "POST",
      });
      await mutateJob(created, { revalidate: false });
      if (created.status === "completed") {
        setBusy(false);
        setMessage(`The latest complete sync was reused (${created.result?.rows ?? 0} rows).`);
        await mutate();
        return;
      }
      setMessage(created.status === "running" ? "Search Console sync is running." : "Search Console sync is queued.");
    } catch (requestError) {
      setBusy(false);
      setMessage(
        requestError instanceof OperatorApiError
          ? requestError.message
          : "Search Console synchronization could not be started.",
      );
    }
  }

  async function startInspection() {
    setInspectionBusy(true);
    setInspectionMessage("");
    try {
      const created = await apiFetch<SyncJob>(
        `/integrations/google-data/url-inspection/${siteId}`,
        { method: "POST", body: JSON.stringify({ urls: [] }) },
      );
      await mutateInspectionJob(created, { revalidate: false });
      if (created.status === "completed") {
        setInspectionBusy(false);
        setInspectionMessage(
          `The latest inspection was reused (${created.result?.processed ?? 0} URLs).`,
        );
        await Promise.all([mutateInspections(), mutate()]);
        return;
      }
      setInspectionMessage(
        created.status === "running"
          ? "URL Inspection is running."
          : "URL Inspection is queued.",
      );
    } catch (requestError) {
      setInspectionBusy(false);
      setInspectionMessage(
        requestError instanceof OperatorApiError
          ? requestError.message
          : "URL Inspection could not be started.",
      );
    }
  }

  const syncActive = Boolean(
    busy || (job && !["completed", "failed", "cancelled"].includes(job.status)),
  );
  const inspectionActive = Boolean(
    inspectionBusy ||
      (inspectionJob &&
        !["completed", "failed", "cancelled"].includes(inspectionJob.status)),
  );

  return (
    <div className="space-y-5">
      <section className="rounded-[20px] border border-gray-200 bg-white p-5 sm:p-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-gray-500">Search performance</p>
            <h3 className="mt-2 text-2xl font-semibold tracking-[-0.035em]">Durable GSC opportunities</h3>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-gray-600">
              Daily query/page metrics produce low-CTR, page-two, decay, and cannibalization signals. Sync jobs survive restarts and retry with leases.
            </p>
          </div>
          <div className="flex flex-col gap-2 sm:flex-row">
            <button
              type="button"
              onClick={startSync}
              disabled={syncActive}
              className="min-h-11 rounded-full bg-[#202020] px-5 text-sm font-semibold text-white disabled:opacity-50"
            >
              {syncActive ? `Sync ${job?.status || "queued"}…` : "Sync Search Console"}
            </button>
            <button
              type="button"
              onClick={startInspection}
              disabled={inspectionActive}
              className="min-h-11 rounded-full border border-gray-300 bg-white px-5 text-sm font-semibold text-gray-950 disabled:opacity-50"
            >
              {inspectionActive
                ? `Inspect ${inspectionJob?.status || "queued"}…`
                : "Inspect indexation"}
            </button>
          </div>
        </div>
        {message && <p className={`mt-4 text-sm ${job?.status === "failed" ? "text-red-700" : "text-gray-700"}`}>{message}</p>}
        {jobError && <p className="mt-4 text-sm text-red-700">The latest sync status could not be loaded. Retry the sync or refresh this page.</p>}
        {inspectionMessage && (
          <p className={`mt-3 text-sm ${inspectionJob?.status === "failed" ? "text-red-700" : "text-gray-700"}`}>
            {inspectionMessage}
          </p>
        )}
        {inspectionJobError && (
          <p className="mt-3 text-sm text-red-700">
            The latest URL Inspection status could not be loaded. Retry or refresh this page.
          </p>
        )}
      </section>

      {!inspectionError && inspections && inspections.items.length > 0 && (
        <section className="rounded-[20px] border border-gray-200 bg-white p-5 sm:p-6">
          <div className="flex items-end justify-between gap-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-gray-500">
                Google indexation
              </p>
              <h4 className="mt-2 text-xl font-semibold">Latest URL Inspection evidence</h4>
            </div>
            <span className="text-xs text-gray-500">{inspections.total} URLs</span>
          </div>
          <div className="mt-4 grid gap-3 lg:grid-cols-2">
            {inspections.items.map((item) => (
              <article key={item.id} className="rounded-2xl bg-[#f9f7f3] p-4">
                <div className="flex items-start justify-between gap-3">
                  <p className="min-w-0 truncate text-sm font-semibold" title={item.inspection_url}>
                    {item.inspection_url}
                  </p>
                  <span
                    className={`shrink-0 rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase ${
                      item.verdict === "PASS"
                        ? "bg-emerald-100 text-emerald-800"
                        : "bg-amber-100 text-amber-900"
                    }`}
                  >
                    {item.verdict.replaceAll("_", " ")}
                  </span>
                </div>
                <p className="mt-2 text-xs text-gray-600">
                  {item.coverage_state || "No coverage state returned"}
                </p>
                <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-gray-600">
                  {item.indexing_state && <span>{item.indexing_state.replaceAll("_", " ")}</span>}
                  {item.page_fetch_state && <span>fetch: {item.page_fetch_state.replaceAll("_", " ")}</span>}
                  {item.robots_txt_state && <span>robots: {item.robots_txt_state.replaceAll("_", " ")}</span>}
                </div>
                {item.google_canonical && item.user_canonical && item.google_canonical !== item.user_canonical && (
                  <p className="mt-3 text-xs text-amber-800">Google selected a different canonical URL.</p>
                )}
              </article>
            ))}
          </div>
        </section>
      )}

      {error && <div className="rounded-2xl border border-amber-200 bg-amber-50 p-5 text-sm text-amber-900">Connect and configure a Search Console property to load opportunities.</div>}
      {!data && !error && <div className="h-40 animate-pulse rounded-[20px] bg-gray-100" />}
      {data?.items.length === 0 && <div className="rounded-[20px] border border-dashed border-gray-300 bg-white p-8 text-center text-sm text-gray-600">No active opportunities yet. Run the first durable Search Console sync.</div>}
      <div className="grid gap-4 lg:grid-cols-2">
        {data?.items.map((item) => (
          <article key={item.id} className="rounded-[20px] border border-gray-200 bg-white p-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-gray-500">{item.opportunity_type.replaceAll("_", " ")}</p>
                <h4 className="mt-2 font-semibold text-gray-950">{item.title}</h4>
              </div>
              <span className="rounded-full bg-[#f3f0e8] px-3 py-1 text-xs font-semibold">{item.priority_score}</span>
            </div>
            {item.page_url && <p className="mt-3 truncate text-xs text-gray-500">{item.page_url}</p>}
            <div className="mt-4 flex flex-wrap gap-2 text-xs text-gray-600">
              <span className="rounded-full border border-gray-200 px-2.5 py-1">confidence {item.confidence_score}</span>
              {typeof item.metrics.clicks === "number" && <span className="rounded-full border border-gray-200 px-2.5 py-1">{item.metrics.clicks} clicks</span>}
              {typeof item.metrics.impressions === "number" && <span className="rounded-full border border-gray-200 px-2.5 py-1">{item.metrics.impressions} impressions</span>}
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}
