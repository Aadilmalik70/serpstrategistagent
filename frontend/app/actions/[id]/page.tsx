"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useSession } from "next-auth/react";
import { useState } from "react";
import useSWR from "swr";

import { apiFetch, OperatorApiError } from "@/lib/api";

type ActionEvent = {
  id: string;
  event_type: string;
  from_status: string | null;
  to_status: string | null;
  actor_type: string;
  payload: Record<string, unknown>;
  created_at: string;
};

type OperatorAction = {
  id: string;
  status: string;
  title: string;
  description: string | null;
  category: string;
  action_type: string;
  evidence: Record<string, unknown>[];
  plan: Record<string, unknown>;
  impact_score: number;
  confidence_score: number;
  effort_score: number;
  risk_score: number;
  risk_level: string;
  approval_policy: { mode?: string; reasons?: string[]; allowed_roles?: string[] };
  requires_approval: boolean;
  execution_target: Record<string, unknown>;
  proposed_diff: Record<string, unknown>;
  rollback_plan: Record<string, unknown>;
  measurement_plan: Record<string, unknown>;
  validation_checklist: Array<Record<string, unknown> | string>;
  rejection_reason: string | null;
  version: number;
  created_at: string;
  proposed_at: string | null;
  approved_at: string | null;
  events: ActionEvent[];
};

function panel(label: string, value: unknown) {
  return (
    <section className="rounded-[20px] border border-[rgba(32,32,32,0.12)] bg-white p-5 sm:p-6">
      <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#646464]">{label}</p>
      <pre className="mt-4 overflow-x-auto whitespace-pre-wrap break-words font-sans text-sm leading-6 text-[#454545]">
        {typeof value === "string" ? value : JSON.stringify(value, null, 2)}
      </pre>
    </section>
  );
}

export default function OperatorActionDetailPage() {
  const params = useParams<{ id: string }>();
  const { data: session } = useSession();
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [rejectReason, setRejectReason] = useState("");
  const canManage = session?.workspaceRole === "owner" || session?.workspaceRole === "admin";

  const { data: action, error, isLoading, mutate } = useSWR<OperatorAction>(
    session?.accessToken && session.workspaceId && params.id ? `/operator-actions/${params.id}` : null,
    apiFetch,
  );

  async function transition(kind: "propose" | "approve" | "reject" | "cancel") {
    if (!action) return;
    setBusy(kind);
    setMessage("");
    try {
      const path =
        kind === "approve" || kind === "reject"
          ? `/operator-actions/${action.id}/decision`
          : `/operator-actions/${action.id}/${kind}`;
      const body =
        kind === "approve" || kind === "reject"
          ? {
              expected_version: action.version,
              decision: kind,
              reason: kind === "reject" ? rejectReason : undefined,
            }
          : { expected_version: action.version };
      await apiFetch(path, { method: "POST", body: JSON.stringify(body) });
      await mutate();
      setMessage(
        kind === "propose"
          ? "Policy evaluation completed."
          : kind === "approve"
            ? "Action approved."
            : kind === "reject"
              ? "Action rejected."
              : "Action cancelled.",
      );
    } catch (requestError) {
      setMessage(
        requestError instanceof OperatorApiError
          ? requestError.message
          : "The action transition could not be completed.",
      );
    } finally {
      setBusy(null);
    }
  }

  if (isLoading) {
    return <div className="min-h-screen bg-[#f9f7f3] p-8"><div className="mx-auto h-96 max-w-6xl animate-pulse rounded-[22px] bg-[#f3f0e8]" /></div>;
  }

  if (error || !action) {
    return (
      <div className="min-h-screen bg-[#f9f7f3] p-8 text-[#202020]">
        <div className="mx-auto max-w-3xl rounded-[20px] border border-red-200 bg-red-50 p-8 text-red-800">
          This operator action could not be loaded.
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#f9f7f3] text-[#202020]">
      <header className="border-b border-[rgba(32,32,32,0.12)]">
        <div className="mx-auto flex min-h-[68px] max-w-7xl items-center justify-between gap-4 px-4 sm:px-6 lg:px-8">
          <Link href="/actions" className="inline-flex items-center gap-3 text-sm font-semibold">
            <span className="grid h-9 w-9 place-items-center rounded-full bg-[#202020] text-white">←</span>
            Action queue
          </Link>
          <span className="rounded-full bg-[#202020] px-3 py-1.5 text-xs font-semibold capitalize text-white">
            {action.status.replaceAll("_", " ")}
          </span>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6 sm:py-10 lg:px-8 lg:py-12">
        <section className="rounded-[24px] bg-[#202020] p-6 text-white sm:p-8 lg:p-10">
          <div className="flex flex-col gap-8 lg:flex-row lg:items-end lg:justify-between">
            <div className="max-w-4xl">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-white/55">{action.category} · {action.action_type}</p>
              <h1 className="mt-3 text-[clamp(2.3rem,6vw,4.5rem)] font-semibold leading-[0.97] tracking-[-0.055em]">{action.title}</h1>
              {action.description && <p className="mt-5 max-w-3xl text-base leading-7 text-white/65">{action.description}</p>}
            </div>
            <div className="grid shrink-0 grid-cols-2 gap-2 sm:grid-cols-4">
              {[
                ["Impact", action.impact_score],
                ["Confidence", action.confidence_score],
                ["Effort", action.effort_score],
                ["Risk", action.risk_score],
              ].map(([label, value]) => (
                <div key={String(label)} className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-center">
                  <p className="text-2xl font-semibold">{value}</p>
                  <p className="text-[10px] uppercase tracking-[0.12em] text-white/50">{label}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {message && (
          <div className="mt-5 rounded-2xl border border-[rgba(32,32,32,0.12)] bg-white p-4 text-sm">{message}</div>
        )}

        {canManage && (
          <section className="mt-5 rounded-[20px] border border-[rgba(32,32,32,0.12)] bg-white p-5 sm:p-6">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#646464]">Governance</p>
                <p className="mt-2 text-sm text-[#575757]">
                  Policy mode: <span className="font-semibold text-[#202020]">{action.approval_policy.mode || "Not evaluated"}</span>
                </p>
                {action.approval_policy.reasons?.map((reason) => <p key={reason} className="mt-1 text-xs text-[#8d8d8d]">• {reason}</p>)}
              </div>
              <div className="flex flex-wrap gap-2">
                {action.status === "draft" && (
                  <button onClick={() => transition("propose")} disabled={Boolean(busy)} className="min-h-11 rounded-full bg-[#ea2804] px-5 text-sm font-semibold text-white disabled:opacity-50">
                    {busy === "propose" ? "Evaluating…" : "Run policy & propose"}
                  </button>
                )}
                {action.status === "needs_approval" && (
                  <>
                    <input
                      value={rejectReason}
                      onChange={(event) => setRejectReason(event.target.value)}
                      placeholder="Reason required for rejection"
                      className="h-11 min-w-64 rounded-full border border-[rgba(32,32,32,0.16)] px-4 text-sm"
                    />
                    <button onClick={() => transition("reject")} disabled={Boolean(busy) || !rejectReason.trim()} className="min-h-11 rounded-full border border-red-200 px-5 text-sm font-semibold text-red-700 disabled:opacity-50">Reject</button>
                    <button onClick={() => transition("approve")} disabled={Boolean(busy)} className="min-h-11 rounded-full bg-[#202020] px-5 text-sm font-semibold text-white disabled:opacity-50">Approve</button>
                  </>
                )}
                {["draft", "needs_approval", "approved"].includes(action.status) && (
                  <button onClick={() => transition("cancel")} disabled={Boolean(busy)} className="min-h-11 rounded-full border border-[rgba(32,32,32,0.16)] px-5 text-sm font-semibold disabled:opacity-50">Cancel</button>
                )}
              </div>
            </div>
          </section>
        )}

        <section className="mt-8 grid gap-5 lg:grid-cols-2">
          {panel("Evidence", action.evidence)}
          {panel("Structured plan", action.plan)}
          {panel("Execution target", action.execution_target)}
          {panel("Proposed diff", action.proposed_diff)}
          {panel("Rollback plan", action.rollback_plan)}
          {panel("Measurement plan", action.measurement_plan)}
          {panel("Validation checklist", action.validation_checklist)}
          {panel("Approval policy", action.approval_policy)}
        </section>

        <section className="mt-8 rounded-[20px] border border-[rgba(32,32,32,0.12)] bg-white p-5 sm:p-6">
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#646464]">Append-only audit trail</p>
          <div className="mt-5 space-y-4">
            {action.events.map((event) => (
              <article key={event.id} className="grid gap-2 border-l-2 border-[#ea2804] pl-4 sm:grid-cols-[12rem_1fr]">
                <div>
                  <p className="text-sm font-semibold">{event.event_type.replaceAll("_", " ")}</p>
                  <p className="mt-1 text-xs text-[#8d8d8d]">{new Date(event.created_at).toLocaleString()}</p>
                </div>
                <div>
                  <p className="text-sm text-[#575757]">
                    {event.from_status || "start"} → {event.to_status || "unchanged"} · {event.actor_type}
                  </p>
                  {Object.keys(event.payload).length > 0 && <pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-xs text-[#8d8d8d]">{JSON.stringify(event.payload, null, 2)}</pre>}
                </div>
              </article>
            ))}
          </div>
        </section>
      </main>
    </div>
  );
}
