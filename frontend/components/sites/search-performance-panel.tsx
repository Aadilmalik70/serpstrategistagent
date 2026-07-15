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

type SyncJob = {
  id: string;
  status: string;
  attempt_count: number;
  max_attempts: number;
  result: { rows?: number; opportunities?: number } | null;
  error_message: string | null;
};

export default function SearchPerformancePanel({ siteId }: { siteId: string }) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
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

  const syncActive = Boolean(
    busy || (job && !["completed", "failed", "cancelled"].includes(job.status)),
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
          <button
            type="button"
            onClick={startSync}
            disabled={syncActive}
            className="min-h-11 rounded-full bg-[#202020] px-5 text-sm font-semibold text-white disabled:opacity-50"
          >
            {syncActive ? `Sync ${job?.status || "queued"}…` : "Sync Search Console"}
          </button>
        </div>
        {message && <p className={`mt-4 text-sm ${job?.status === "failed" ? "text-red-700" : "text-gray-700"}`}>{message}</p>}
        {jobError && <p className="mt-4 text-sm text-red-700">The latest sync status could not be loaded. Retry the sync or refresh this page.</p>}
      </section>

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
