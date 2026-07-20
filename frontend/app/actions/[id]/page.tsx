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
  site_id: string;
  source: string;
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
  execution_result: Record<string, unknown> | null;
  rejection_reason: string | null;
  version: number;
  created_at: string;
  proposed_at: string | null;
  approved_at: string | null;
  events: ActionEvent[];
};

type ExecutionJob = {
  id: string;
  action_id: string;
  parent_job_id: string | null;
  job_type: string;
  adapter: string;
  status: string;
  attempt_count: number;
  max_attempts: number;
  error_code: string | null;
  error_message: string | null;
  cancellation_requested: boolean;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
};

type ActionMeasurement = {
  id: string;
  window_days: number;
  status: string;
  outcome: string;
  baseline_metrics: Record<string, number | string | boolean | null>;
  comparison_metrics: Record<string, number | string | boolean | null>;
  delta: Record<string, number>;
  confidence_score: number;
  measured_at: string | null;
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

function jobBadge(status: string) {
  if (status === "succeeded") return "bg-emerald-100 text-emerald-800";
  if (status === "failed") return "bg-red-100 text-red-800";
  if (status === "running") return "bg-blue-100 text-blue-800";
  if (status === "cancelled") return "bg-[#f3f0e8] text-[#646464]";
  return "bg-amber-100 text-amber-900";
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

export default function OperatorActionDetailPage() {
  const params = useParams<{ id: string }>();
  const { data: session } = useSession();
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [rejectReason, setRejectReason] = useState("");
  const canManage = session?.workspaceRole === "owner" || session?.workspaceRole === "admin";
  const canUseApi = Boolean(session?.accessToken && session.workspaceId && params.id);

  const { data: action, error, isLoading, mutate } = useSWR<OperatorAction>(
    canUseApi ? `/operator-actions/${params.id}` : null,
    apiFetch,
  );
  const { data: jobs, mutate: mutateJobs } = useSWR<ExecutionJob[]>(
    canUseApi ? `/execution-jobs?action_id=${params.id}` : null,
    apiFetch,
    { refreshInterval: 4000 },
  );
  const { data: measurements, mutate: mutateMeasurements } = useSWR<ActionMeasurement[]>(
    canUseApi ? `/operator-actions/${params.id}/measurements` : null,
    apiFetch,
  );

  async function refreshAll() {
    await Promise.all([mutate(), mutateJobs(), mutateMeasurements()]);
  }

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
      await refreshAll();
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

  async function queueExecution(kind: "execute" | "rollback") {
    if (!action) return;
    setBusy(kind);
    setMessage("");
    try {
      await apiFetch(`/operator-actions/${action.id}/${kind}`, {
        method: "POST",
        body: JSON.stringify({ expected_version: action.version }),
      });
      await refreshAll();
      setMessage(kind === "execute" ? "Execution job queued." : "Rollback job queued.");
    } catch (requestError) {
      setMessage(
        requestError instanceof OperatorApiError
          ? requestError.message
          : "The execution request could not be queued.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function cancelJob(jobId: string) {
    setBusy(`cancel-${jobId}`);
    setMessage("");
    try {
      await apiFetch(`/execution-jobs/${jobId}/cancel`, { method: "POST" });
      await refreshAll();
      setMessage("Execution cancellation requested.");
    } catch (requestError) {
      setMessage(
        requestError instanceof OperatorApiError
          ? requestError.message
          : "The execution job could not be cancelled.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function refreshMeasurements() {
    if (!action) return;
    setBusy("measurements");
    setMessage("");
    try {
      await apiFetch(`/operator-actions/${action.id}/measurements/refresh`, { method: "POST" });
      await mutateMeasurements();
      setMessage("Measurement outcomes refreshed.");
    } catch (requestError) {
      setMessage(
        requestError instanceof OperatorApiError
          ? requestError.message
          : "Measurement outcomes could not be refreshed.",
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

  const adapter = String(action.execution_target.adapter || action.execution_target.provider || action.execution_target.type || "not configured");
  const patchPlanner = recordValue(action.proposed_diff.planner);
  const patchFiles = Array.isArray(action.proposed_diff.files) ? action.proposed_diff.files : [];
  const plannerStatus = typeof patchPlanner.status === "string" ? patchPlanner.status : null;
  const hasPlannerMetadata = Boolean(plannerStatus);
  const exactPatchReady = adapter === "github" && plannerStatus === "ready" && patchFiles.length > 0;
  const legacyTechnicalSimulation = action.source === "technical_finding_pipeline" && adapter === "simulation" && !hasPlannerMetadata;
  const activeJob = jobs?.find((job) => ["queued", "running", "retry_wait"].includes(job.status));
  const executionEnvelope = recordValue(action.execution_result?.execution);
  const providerExecution = recordValue(executionEnvelope.execution);
  const pullRequestUrl = typeof providerExecution.pull_request_url === "string" ? providerExecution.pull_request_url : null;

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
              {[["Impact", action.impact_score], ["Confidence", action.confidence_score], ["Effort", action.effort_score], ["Risk", action.risk_score]].map(([label, value]) => (
                <div key={String(label)} className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-center">
                  <p className="text-2xl font-semibold">{value}</p>
                  <p className="text-[10px] uppercase tracking-[0.12em] text-white/50">{label}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {message && <div className="mt-5 rounded-2xl border border-[rgba(32,32,32,0.12)] bg-white p-4 text-sm">{message}</div>}

        {canManage && (
          <section className="mt-5 rounded-[20px] border border-[rgba(32,32,32,0.12)] bg-white p-5 sm:p-6">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#646464]">Governance</p>
                <p className="mt-2 text-sm text-[#575757]">Policy mode: <span className="font-semibold text-[#202020]">{action.approval_policy.mode || "Not evaluated"}</span></p>
                {action.approval_policy.reasons?.map((reason) => <p key={reason} className="mt-1 text-xs text-[#8d8d8d]">• {reason}</p>)}
              </div>
              <div className="flex flex-wrap gap-2">
                {action.status === "draft" && <button onClick={() => transition("propose")} disabled={Boolean(busy)} className="min-h-11 rounded-full bg-[#ea2804] px-5 text-sm font-semibold text-white disabled:opacity-50">{busy === "propose" ? "Evaluating…" : "Run policy & propose"}</button>}
                {action.status === "needs_approval" && <>
                  <input value={rejectReason} onChange={(event) => setRejectReason(event.target.value)} placeholder="Reason required for rejection" className="h-11 min-w-64 rounded-full border border-[rgba(32,32,32,0.16)] px-4 text-sm" />
                  <button onClick={() => transition("reject")} disabled={Boolean(busy) || !rejectReason.trim()} className="min-h-11 rounded-full border border-red-200 px-5 text-sm font-semibold text-red-700 disabled:opacity-50">Reject</button>
                  <button onClick={() => transition("approve")} disabled={Boolean(busy)} className="min-h-11 rounded-full bg-[#202020] px-5 text-sm font-semibold text-white disabled:opacity-50">Approve</button>
                </>}
                {action.status === "approved" && !legacyTechnicalSimulation && <button onClick={() => queueExecution("execute")} disabled={Boolean(busy)} className="min-h-11 rounded-full bg-[#ea2804] px-5 text-sm font-semibold text-white disabled:opacity-50">{busy === "execute" ? "Queueing…" : "Queue execution"}</button>}
                {action.status === "approved" && legacyTechnicalSimulation && <Link href={`/sites/${action.site_id}`} className="inline-flex min-h-11 items-center rounded-full bg-[#202020] px-5 text-sm font-semibold text-white">Re-crawl & refresh finding</Link>}
                {action.status === "succeeded" && <button onClick={() => queueExecution("rollback")} disabled={Boolean(busy)} className="min-h-11 rounded-full bg-[#202020] px-5 text-sm font-semibold text-white disabled:opacity-50">{busy === "rollback" ? "Queueing…" : "Queue rollback"}</button>}
                {["draft", "needs_approval", "approved"].includes(action.status) && <button onClick={() => transition("cancel")} disabled={Boolean(busy)} className="min-h-11 rounded-full border border-[rgba(32,32,32,0.16)] px-5 text-sm font-semibold disabled:opacity-50">Cancel</button>}
              </div>
            </div>
          </section>
        )}

        {hasPlannerMetadata && <section className={`mt-5 rounded-[20px] border p-5 sm:p-6 ${exactPatchReady ? "border-emerald-200 bg-emerald-50" : "border-[rgba(32,32,32,0.12)] bg-white"}`}>
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#646464]">Repository patch plan</p>
          <div className="mt-2 flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <h2 className="text-xl font-semibold tracking-[-0.03em]">{exactPatchReady ? "Exact GitHub patch ready for review" : "Simulation fallback"}</h2>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-[#575757]">
                {exactPatchReady
                  ? `The planner resolved ${String(patchPlanner.source_path || action.execution_target.source_path || "one source file")} and produced ${String(patchPlanner.changed_lines || "a bounded number of")} changed lines. Review the complete replacement content below before approval.`
                  : String(patchPlanner.reason || "No exact repository patch was produced for this action.")}
              </p>
            </div>
            <div className="flex flex-wrap gap-2 text-xs">
              <span className="rounded-full bg-white px-3 py-1.5 font-semibold">{adapter}</span>
              {Boolean(patchPlanner.model) && <span className="rounded-full bg-white px-3 py-1.5">{String(patchPlanner.model)}</span>}
              {patchFiles.length > 0 && <span className="rounded-full bg-white px-3 py-1.5">{patchFiles.length} file{patchFiles.length === 1 ? "" : "s"}</span>}
            </div>
          </div>
        </section>}

        {legacyTechnicalSimulation && <section className="mt-5 rounded-[20px] border border-amber-200 bg-amber-50 p-5 sm:p-6">
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-amber-800">Legacy technical action</p>
          <h2 className="mt-2 text-xl font-semibold tracking-[-0.03em]">Re-crawl before creating a repository patch</h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-amber-950/75">
            This immutable action predates repository-aware planning and will not convert in place. Re-crawl the site and refresh Technical Findings. If the finding still reproduces, the pipeline will create a new reviewed action; if it no longer reproduces, this action will be cancelled.
          </p>
          <Link href={`/sites/${action.site_id}`} className="mt-4 inline-flex min-h-10 items-center rounded-full bg-[#202020] px-4 text-sm font-semibold text-white">Open site findings</Link>
        </section>}

        <section className="mt-5 rounded-[20px] border border-[rgba(32,32,32,0.12)] bg-white p-5 sm:p-6">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#646464]">Durable execution</p>
              <h2 className="mt-2 text-2xl font-semibold tracking-[-0.035em]">{legacyTechnicalSimulation ? "Execution unavailable for this legacy action" : "Jobs, leases and validation"}</h2>
              <p className="mt-2 text-sm text-[#646464]">
                {legacyTechnicalSimulation
                  ? "This historical record retains its original simulation target for audit integrity, but it cannot be queued. Re-crawl and refresh the finding to resolve it or create a new repository-aware action."
                  : <>Adapter: <span className="font-semibold text-[#202020]">{adapter}</span>. GitHub execution creates a human-reviewed draft PR from an approved exact file plan; WordPress execution and autonomous merge remain disabled.</>}
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              {pullRequestUrl && <a href={pullRequestUrl} target="_blank" rel="noreferrer" className="inline-flex min-h-10 items-center rounded-full bg-[#202020] px-4 text-sm font-semibold text-white">Open draft PR ↗</a>}
              {activeJob && canManage && <button onClick={() => cancelJob(activeJob.id)} disabled={Boolean(busy)} className="min-h-10 rounded-full border border-red-200 px-4 text-sm font-semibold text-red-700 disabled:opacity-50">Cancel active job</button>}
            </div>
          </div>
          <div className="mt-5 space-y-3">
            {!jobs && <div className="h-24 animate-pulse rounded-2xl bg-[#f3f0e8]" />}
            {jobs?.length === 0 && <div className="rounded-2xl border border-dashed border-[rgba(32,32,32,0.2)] p-5 text-sm text-[#646464]">No execution jobs have been created for this action.</div>}
            {jobs?.map((job) => <article key={job.id} className="rounded-2xl border border-[rgba(32,32,32,0.1)] bg-[#f9f7f3] p-4 sm:p-5">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="font-semibold capitalize">{job.job_type}</p>
                    <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold capitalize ${jobBadge(job.status)}`}>{job.status.replaceAll("_", " ")}</span>
                  </div>
                  <p className="mt-1 text-xs text-[#8d8d8d]">{job.adapter} · attempt {job.attempt_count}/{job.max_attempts} · {new Date(job.created_at).toLocaleString()}</p>
                  {job.error_message && <p className="mt-2 text-sm text-red-700">{job.error_code}: {job.error_message}</p>}
                </div>
                <Link href={`/execution-jobs/${job.id}`} className="text-sm font-semibold text-[#ea2804]">View job →</Link>
              </div>
            </article>)}
          </div>
        </section>

        <section className="mt-5 rounded-[20px] border border-[rgba(32,32,32,0.12)] bg-white p-5 sm:p-6">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#646464]">Before / after measurement</p>
              <h2 className="mt-2 text-2xl font-semibold tracking-[-0.035em]">7–90 day action outcomes</h2>
              <p className="mt-2 text-sm text-[#646464]">Search Console baselines are frozen when execution is queued. Completed windows classify impact as positive, neutral, negative, or insufficient data.</p>
            </div>
            {canManage && <button type="button" onClick={() => void refreshMeasurements()} disabled={busy === "measurements"} className="min-h-10 rounded-full border border-[rgba(32,32,32,0.16)] px-4 text-sm font-semibold disabled:opacity-50">{busy === "measurements" ? "Refreshing…" : "Refresh outcomes"}</button>}
          </div>
          <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            {measurements?.map((measurement) => (
              <article key={measurement.id} className="rounded-2xl bg-[#f9f7f3] p-4">
                <div className="flex items-center justify-between gap-2">
                  <p className="font-semibold">{measurement.window_days} days</p>
                  <span className={`rounded-full px-2 py-1 text-[10px] font-semibold uppercase ${measurement.outcome === "positive" ? "bg-emerald-100 text-emerald-800" : measurement.outcome === "negative" ? "bg-red-100 text-red-800" : "bg-[#ebe7dd] text-[#646464]"}`}>{measurement.outcome.replaceAll("_", " ")}</span>
                </div>
                <p className="mt-3 text-xs text-[#646464]">Baseline clicks</p>
                <p className="text-lg font-semibold">{measurement.baseline_metrics.clicks ?? 0}</p>
                <p className="mt-2 text-xs text-[#646464]">After clicks</p>
                <p className="text-lg font-semibold">{measurement.status === "measured" ? measurement.comparison_metrics.clicks ?? 0 : "Waiting"}</p>
                <p className="mt-2 text-[10px] uppercase tracking-[0.1em] text-[#8d8d8d]">confidence {measurement.confidence_score}</p>
              </article>
            ))}
            {measurements?.length === 0 && <p className="col-span-full text-sm text-[#646464]">{adapter === "simulation" ? "Simulation-only actions do not create outcome measurements or influence learning." : "Measurement baselines will be frozen immediately before execution."}</p>}
          </div>
        </section>

        <section className="mt-8 grid gap-5 lg:grid-cols-2">
          {panel("Evidence", action.evidence)}
          {panel("Structured plan", action.plan)}
          {panel("Execution target", action.execution_target)}
          {panel("Proposed diff", action.proposed_diff)}
          {panel("Rollback plan", action.rollback_plan)}
          {panel("Measurement plan", action.measurement_plan)}
          {panel("Validation checklist", action.validation_checklist)}
          {panel("Approval policy", action.approval_policy)}
          {action.execution_result && panel("Execution result", action.execution_result)}
        </section>

        <section className="mt-8 rounded-[20px] border border-[rgba(32,32,32,0.12)] bg-white p-5 sm:p-6">
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#646464]">Append-only audit trail</p>
          <div className="mt-5 space-y-4">
            {action.events.map((event) => <article key={event.id} className="grid gap-2 border-l-2 border-[#ea2804] pl-4 sm:grid-cols-[12rem_1fr]">
              <div><p className="text-sm font-semibold">{event.event_type.replaceAll("_", " ")}</p><p className="mt-1 text-xs text-[#8d8d8d]">{new Date(event.created_at).toLocaleString()}</p></div>
              <div><p className="text-sm text-[#575757]">{event.from_status || "start"} → {event.to_status || "unchanged"} · {event.actor_type}</p>{Object.keys(event.payload).length > 0 && <pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-xs text-[#8d8d8d]">{JSON.stringify(event.payload, null, 2)}</pre>}</div>
            </article>)}
          </div>
        </section>
      </main>
    </div>
  );
}
