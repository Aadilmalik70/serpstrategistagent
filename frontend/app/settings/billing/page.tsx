"use client";

import Link from "next/link";
import { useSession } from "next-auth/react";
import { useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";

import { apiFetch, OperatorApiError } from "@/lib/api";

type PlanId = "audit" | "growth" | "scale";

type PlanDefinition = {
  id: PlanId;
  name: string;
  description: string;
  entitlements: Record<string, number>;
  checkout_available: boolean;
};

type UsageMetric = {
  used: number;
  limit: number;
};

type BillingSummary = {
  plan: PlanId;
  status: string;
  cancel_at_period_end: boolean;
  current_period_start: string;
  current_period_end: string;
  entitlements: Record<string, number>;
  usage: Record<string, UsageMetric>;
  stripe_customer: boolean;
  stripe_configured: boolean;
};

const metricLabels: Record<string, string> = {
  monthly_crawl_pages: "Crawl pages",
  ai_requests: "AI requests",
  ai_tokens: "AI tokens",
  serp_queries: "Live SERP queries",
};

const entitlementLabels: Record<string, string> = {
  sites: "sites",
  monthly_crawl_pages: "crawl pages / month",
  ai_requests: "AI requests / month",
  ai_tokens: "AI tokens / month",
  serp_queries: "SERP queries / month",
  team_members: "collaborator seats",
};

function formatNumber(value: number) {
  return new Intl.NumberFormat("en-US", { notation: value >= 100_000 ? "compact" : "standard" }).format(value);
}

export default function BillingPage() {
  const { data: session } = useSession();
  const [action, setAction] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [checkoutNotice, setCheckoutNotice] = useState<string | null>(null);
  const checkoutConfirmationStarted = useRef(false);

  const { data: summary, mutate } = useSWR<BillingSummary>(
    session?.accessToken && session.workspaceId ? "/billing/summary" : null,
    apiFetch,
  );
  const { data: plans } = useSWR<PlanDefinition[]>(
    session?.accessToken && session.workspaceId ? "/billing/plans" : null,
    apiFetch,
  );

  useEffect(() => {
    if (
      checkoutConfirmationStarted.current ||
      !session?.accessToken ||
      !session.workspaceId
    ) {
      return;
    }

    const params = new URLSearchParams(window.location.search);
    if (params.get("checkout") !== "success") return;

    const sessionId = params.get("session_id");
    if (!sessionId) return;

    checkoutConfirmationStarted.current = true;

    void apiFetch<BillingSummary>("/billing/checkout/confirm", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId }),
    })
      .then((updated) => {
        void mutate(updated, false);
        setCheckoutNotice(`${updated.plan[0].toUpperCase()}${updated.plan.slice(1)} plan activated.`);
        window.history.replaceState({}, "", window.location.pathname);
      })
      .catch((caught) => {
        setCheckoutNotice(null);
        setError(
          caught instanceof OperatorApiError
            ? caught.message
            : "Checkout succeeded, but the subscription could not be synchronized.",
        );
      });
  }, [mutate, session?.accessToken, session?.workspaceId]);

  const periodLabel = useMemo(() => {
    if (!summary) return "Current billing period";
    const start = new Date(summary.current_period_start).toLocaleDateString();
    const end = new Date(summary.current_period_end).toLocaleDateString();
    return `${start} – ${end}`;
  }, [summary]);

  async function openCheckout(plan: "growth" | "scale") {
    setAction(`checkout-${plan}`);
    setError(null);
    try {
      const response = await apiFetch<{ url: string }>("/billing/checkout", {
        method: "POST",
        body: JSON.stringify({ plan }),
      });
      window.location.assign(response.url);
    } catch (caught) {
      setError(caught instanceof OperatorApiError ? caught.message : "Checkout could not be started.");
      setAction(null);
    }
  }

  async function openPortal() {
    setAction("portal");
    setError(null);
    try {
      const response = await apiFetch<{ url: string }>("/billing/portal", { method: "POST" });
      window.location.assign(response.url);
    } catch (caught) {
      setError(caught instanceof OperatorApiError ? caught.message : "Billing portal could not be opened.");
      setAction(null);
    }
  }

  return (
    <div className="min-h-screen bg-[#f9f7f3] text-[#202020]">
      <header className="border-b border-[rgba(32,32,32,0.12)]">
        <div className="mx-auto flex min-h-[68px] max-w-6xl items-center justify-between gap-4 px-4 sm:px-6 lg:px-8">
          <Link href="/settings" className="inline-flex items-center gap-3 text-sm font-semibold">
            <span className="grid h-9 w-9 place-items-center rounded-full bg-[#202020] text-white">←</span>
            Settings
          </Link>
          <span className="max-w-[12rem] truncate text-sm text-[#646464] sm:max-w-none">
            {session?.user?.email}
          </span>
        </div>
      </header>

      <section className="operator-grid border-b border-[rgba(32,32,32,0.12)] bg-[#f3f0e8]">
        <div className="mx-auto max-w-6xl px-4 py-12 sm:px-6 sm:py-16 lg:px-8">
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#646464]">Billing & capacity</p>
          <h1 className="mt-3 max-w-4xl text-[clamp(2.6rem,7vw,4.8rem)] font-semibold leading-[0.96] tracking-[-0.055em]">
            Usage limits that stay server-enforced.
          </h1>
          <p className="mt-5 max-w-2xl text-base leading-7 text-[#575757] sm:text-lg">
            Review the active workspace plan, monthly provider consumption and the limits applied before operator work runs.
          </p>
        </div>
      </section>

      <main className="mx-auto max-w-6xl space-y-8 px-4 py-8 sm:px-6 sm:py-10 lg:px-8 lg:py-12">
        {error && (
          <div className="rounded-2xl border border-[#ea2804]/25 bg-[#fff2ee] px-5 py-4 text-sm text-[#9e1f08]">
            {error}
          </div>
        )}
        {checkoutNotice && (
          <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-5 py-4 text-sm text-emerald-800">
            {checkoutNotice}
          </div>
        )}

        <section className="grid gap-5 lg:grid-cols-[1.1fr_1.9fr]">
          <article className="rounded-[22px] bg-[#202020] p-6 text-white sm:p-8">
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-white/55">Current workspace plan</p>
            <div className="mt-5 flex items-start justify-between gap-4">
              <div>
                <h2 className="text-4xl font-semibold capitalize tracking-[-0.05em]">{summary?.plan ?? "—"}</h2>
                <p className="mt-2 text-sm capitalize text-white/60">{summary?.status ?? "Loading"}</p>
              </div>
              <span className="rounded-full bg-[#ea2804] px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.08em]">
                {summary?.cancel_at_period_end ? "Cancels later" : "Active limits"}
              </span>
            </div>
            <p className="mt-8 text-sm leading-6 text-white/65">{periodLabel}</p>
            {summary?.stripe_customer && (
              <button
                type="button"
                onClick={openPortal}
                disabled={action !== null}
                className="mt-6 w-full rounded-full border border-white/20 px-5 py-3 text-sm font-semibold transition hover:bg-white hover:text-[#202020] disabled:cursor-not-allowed disabled:opacity-50"
              >
                {action === "portal" ? "Opening portal…" : "Manage subscription"}
              </button>
            )}
          </article>

          <article className="rounded-[22px] border border-[rgba(32,32,32,0.12)] bg-white p-6 sm:p-8">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#646464]">Period consumption</p>
                <h2 className="mt-2 text-2xl font-semibold tracking-[-0.035em]">Workspace usage</h2>
              </div>
              <button type="button" onClick={() => mutate()} className="text-sm font-semibold text-[#ea2804]">
                Refresh usage
              </button>
            </div>

            <div className="mt-7 grid gap-5 sm:grid-cols-2">
              {Object.entries(summary?.usage ?? {}).map(([metric, values]) => {
                const percent = values.limit > 0 ? Math.min(100, Math.round((values.used / values.limit) * 100)) : 0;
                return (
                  <div key={metric} className="rounded-2xl bg-[#f3f0e8] p-5">
                    <div className="flex items-start justify-between gap-3">
                      <p className="font-semibold">{metricLabels[metric] ?? metric}</p>
                      <span className="text-xs font-semibold text-[#646464]">{percent}%</span>
                    </div>
                    <p className="mt-3 text-2xl font-semibold tracking-[-0.04em]">
                      {formatNumber(values.used)} <span className="text-sm font-medium text-[#777]">/ {formatNumber(values.limit)}</span>
                    </p>
                    <div className="mt-4 h-2 overflow-hidden rounded-full bg-white">
                      <div className="h-full rounded-full bg-[#ea2804]" style={{ width: `${percent}%` }} />
                    </div>
                  </div>
                );
              })}
              {!summary && [1, 2, 3, 4].map((item) => <div key={item} className="h-32 animate-pulse rounded-2xl bg-[#f3f0e8]" />)}
            </div>
          </article>
        </section>

        <section>
          <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#646464]">Plans</p>
              <h2 className="mt-2 text-3xl font-semibold tracking-[-0.045em]">Choose operating capacity</h2>
            </div>
            {!summary?.stripe_configured && (
              <span className="rounded-full bg-[#fff2cc] px-3 py-1.5 text-xs font-semibold text-[#765c00]">
                Stripe configuration required
              </span>
            )}
          </div>

          <div className="mt-6 grid gap-5 lg:grid-cols-3">
            {plans?.map((plan) => {
              const current = summary?.plan === plan.id;
              return (
                <article
                  key={plan.id}
                  className={`rounded-[22px] border p-6 sm:p-7 ${
                    current ? "border-[#ea2804] bg-[#fff8f5]" : "border-[rgba(32,32,32,0.12)] bg-white"
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#646464]">{plan.id}</p>
                      <h3 className="mt-2 text-3xl font-semibold tracking-[-0.045em]">{plan.name}</h3>
                    </div>
                    {current && <span className="rounded-full bg-[#ea2804] px-3 py-1 text-xs font-semibold text-white">Current</span>}
                  </div>
                  <p className="mt-4 min-h-14 text-sm leading-6 text-[#646464]">{plan.description}</p>
                  <ul className="mt-6 space-y-3 text-sm">
                    {Object.entries(plan.entitlements).map(([metric, value]) => (
                      <li key={metric} className="flex items-center justify-between gap-3 border-b border-[rgba(32,32,32,0.08)] pb-3">
                        <span className="text-[#646464]">{entitlementLabels[metric] ?? metric}</span>
                        <strong>{formatNumber(value)}</strong>
                      </li>
                    ))}
                  </ul>
                  {plan.checkout_available && !current && (
                    <button
                      type="button"
                      onClick={() => openCheckout(plan.id as "growth" | "scale")}
                      disabled={!summary?.stripe_configured || action !== null}
                      className="mt-7 w-full rounded-full bg-[#202020] px-5 py-3 text-sm font-semibold text-white transition hover:bg-[#ea2804] disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      {action === `checkout-${plan.id}` ? "Opening checkout…" : `Choose ${plan.name}`}
                    </button>
                  )}
                  {plan.id === "audit" && !current && (
                    <p className="mt-7 text-center text-xs text-[#777]">Audit is the automatic fallback after a paid plan ends.</p>
                  )}
                </article>
              );
            })}
            {!plans && [1, 2, 3].map((item) => <div key={item} className="h-[32rem] animate-pulse rounded-[22px] bg-white" />)}
          </div>
        </section>
      </main>
    </div>
  );
}
