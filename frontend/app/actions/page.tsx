"use client";

import Link from "next/link";
import { useSession } from "next-auth/react";
import { useMemo, useState } from "react";
import useSWR from "swr";

import { apiFetch } from "@/lib/api";

type OperatorAction = {
  id: string;
  site_id: string;
  action_type: string;
  category: string;
  status: string;
  title: string;
  description: string | null;
  impact_score: number;
  confidence_score: number;
  effort_score: number;
  risk_score: number;
  risk_level: string;
  requires_approval: boolean;
  approval_policy: { mode?: string; reasons?: string[] };
  created_at: string;
};

type QueueResponse = {
  items: OperatorAction[];
  total: number;
  counts_by_status: Record<string, number>;
  counts_by_risk: Record<string, number>;
};

const statusOptions = [
  ["", "All"],
  ["draft", "Draft"],
  ["needs_approval", "Needs approval"],
  ["approved", "Approved"],
  ["blocked", "Blocked"],
  ["succeeded", "Succeeded"],
  ["failed", "Failed"],
] as const;

function badgeClass(value: string) {
  if (value === "high" || value === "blocked" || value === "failed") return "bg-red-100 text-red-800";
  if (value === "medium" || value === "needs_approval") return "bg-amber-100 text-amber-900";
  if (value === "low" || value === "approved" || value === "succeeded") return "bg-emerald-100 text-emerald-900";
  return "bg-[#f3f0e8] text-[#575757]";
}

export default function OperatorActionsPage() {
  const { data: session } = useSession();
  const [statusFilter, setStatusFilter] = useState("");
  const [riskFilter, setRiskFilter] = useState("");
  const query = useMemo(() => {
    const params = new URLSearchParams();
    if (statusFilter) params.set("status", statusFilter);
    if (riskFilter) params.set("risk_level", riskFilter);
    const suffix = params.toString();
    return `/operator-actions${suffix ? `?${suffix}` : ""}`;
  }, [riskFilter, statusFilter]);

  const { data, error, isLoading } = useSWR<QueueResponse>(
    session?.accessToken && session.workspaceId ? query : null,
    apiFetch,
  );

  return (
    <div className="min-h-screen bg-[#f9f7f3] text-[#202020]">
      <header className="border-b border-[rgba(32,32,32,0.12)] bg-[#f9f7f3]">
        <div className="mx-auto flex min-h-[68px] max-w-7xl items-center justify-between gap-4 px-4 sm:px-6 lg:px-8">
          <Link href="/" className="inline-flex items-center gap-3 text-sm font-semibold">
            <span className="grid h-9 w-9 place-items-center rounded-full bg-[#202020] text-white">←</span>
            Operator console
          </Link>
          <span className="rounded-full bg-[#f3f0e8] px-3 py-1.5 text-xs font-semibold capitalize text-[#575757]">
            {session?.workspaceRole || "workspace"}
          </span>
        </div>
      </header>

      <section className="operator-grid border-b border-[rgba(32,32,32,0.12)] bg-[#f3f0e8]">
        <div className="mx-auto max-w-7xl px-4 py-12 sm:px-6 sm:py-16 lg:px-8">
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#646464]">Governed action system</p>
          <h1 className="mt-3 max-w-4xl text-[clamp(2.8rem,7vw,5rem)] font-semibold leading-[0.95] tracking-[-0.06em]">
            Every change earns its way into execution.
          </h1>
          <p className="mt-5 max-w-2xl text-base leading-7 text-[#575757] sm:text-lg">
            Evidence, risk, approval policy, validation and rollback stay attached to the action from proposal through measurement.
          </p>
        </div>
      </section>

      <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6 sm:py-10 lg:px-8 lg:py-12">
        <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[
            ["Total", data?.total],
            ["Needs approval", data?.counts_by_status.needs_approval || 0],
            ["Approved", data?.counts_by_status.approved || 0],
            ["Blocked", data?.counts_by_status.blocked || 0],
          ].map(([label, value]) => (
            <div key={String(label)} className="rounded-[18px] border border-[rgba(32,32,32,0.12)] bg-white p-5">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#646464]">{label}</p>
              <p className="mt-3 text-3xl font-semibold tracking-[-0.04em]">{value ?? "—"}</p>
            </div>
          ))}
        </section>

        <section className="mt-8 rounded-[20px] border border-[rgba(32,32,32,0.12)] bg-white p-4 sm:p-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex flex-wrap gap-2">
              {statusOptions.map(([value, label]) => (
                <button
                  key={value || "all"}
                  type="button"
                  onClick={() => setStatusFilter(value)}
                  className={`min-h-10 rounded-full px-4 text-sm font-semibold transition ${statusFilter === value ? "bg-[#202020] text-white" : "bg-[#f3f0e8] text-[#575757] hover:text-[#202020]"}`}
                >
                  {label}
                </button>
              ))}
            </div>
            <select
              value={riskFilter}
              onChange={(event) => setRiskFilter(event.target.value)}
              className="h-10 rounded-full border border-[rgba(32,32,32,0.16)] bg-white px-4 text-sm font-semibold"
            >
              <option value="">All risk levels</option>
              <option value="low">Low risk</option>
              <option value="medium">Medium risk</option>
              <option value="high">High risk</option>
            </select>
          </div>
        </section>

        <section className="mt-5 space-y-4">
          {isLoading && [1, 2, 3].map((item) => <div key={item} className="h-44 animate-pulse rounded-[20px] bg-[#f3f0e8]" />)}
          {error && (
            <div className="rounded-[20px] border border-red-200 bg-red-50 p-6 text-red-800">
              The governed action queue could not be loaded.
            </div>
          )}
          {!isLoading && !error && data?.items.length === 0 && (
            <div className="rounded-[20px] border border-dashed border-[rgba(32,32,32,0.22)] bg-white px-6 py-14 text-center">
              <p className="font-semibold">No actions match this view</p>
              <p className="mt-2 text-sm text-[#646464]">Deterministic findings and operator plans will appear here when created.</p>
            </div>
          )}
          {data?.items.map((action) => (
            <Link
              key={action.id}
              href={`/actions/${action.id}`}
              className="block rounded-[20px] border border-[rgba(32,32,32,0.12)] bg-white p-5 transition hover:-translate-y-0.5 hover:border-[rgba(32,32,32,0.3)] sm:p-6"
            >
              <div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold capitalize ${badgeClass(action.status)}`}>
                      {action.status.replaceAll("_", " ")}
                    </span>
                    <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold capitalize ${badgeClass(action.risk_level)}`}>
                      {action.risk_level} risk
                    </span>
                    <span className="text-xs uppercase tracking-[0.12em] text-[#8d8d8d]">{action.category}</span>
                  </div>
                  <h2 className="mt-3 text-xl font-semibold tracking-[-0.03em] sm:text-2xl">{action.title}</h2>
                  {action.description && <p className="mt-2 line-clamp-2 max-w-3xl text-sm leading-6 text-[#646464]">{action.description}</p>}
                </div>
                <div className="grid shrink-0 grid-cols-3 gap-2 text-center">
                  {[
                    ["Impact", action.impact_score],
                    ["Confidence", action.confidence_score],
                    ["Risk", action.risk_score],
                  ].map(([label, value]) => (
                    <div key={String(label)} className="min-w-20 rounded-2xl bg-[#f3f0e8] px-3 py-3">
                      <p className="text-lg font-semibold">{value}</p>
                      <p className="text-[10px] uppercase tracking-[0.1em] text-[#646464]">{label}</p>
                    </div>
                  ))}
                </div>
              </div>
            </Link>
          ))}
        </section>
      </main>
    </div>
  );
}
