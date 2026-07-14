"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useSession } from "next-auth/react";
import useSWR from "swr";

import { apiFetch } from "@/lib/api";

type Attempt = {
  id: string;
  attempt_number: number;
  worker_id: string;
  status: string;
  result: Record<string, unknown>;
  error_code: string | null;
  error_message: string | null;
  started_at: string;
  completed_at: string | null;
};

type Snapshot = {
  id: string;
  snapshot_type: string;
  adapter: string;
  external_revision: string | null;
  checksum: string;
  data: Record<string, unknown>;
  created_at: string;
};

type JobDetail = {
  id: string;
  action_id: string;
  parent_job_id: string | null;
  job_type: string;
  adapter: string;
  status: string;
  attempt_count: number;
  max_attempts: number;
  payload: Record<string, unknown>;
  result: Record<string, unknown>;
  error_code: string | null;
  error_message: string | null;
  run_after: string;
  lease_owner: string | null;
  lease_expires_at: string | null;
  cancellation_requested: boolean;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  attempts: Attempt[];
  snapshots: Snapshot[];
};

function jsonPanel(label: string, value: unknown) {
  return (
    <section className="rounded-[20px] border border-[rgba(32,32,32,0.12)] bg-white p-5 sm:p-6">
      <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#646464]">{label}</p>
      <pre className="mt-4 overflow-x-auto whitespace-pre-wrap break-words text-xs leading-6 text-[#575757]">{JSON.stringify(value, null, 2)}</pre>
    </section>
  );
}

export default function ExecutionJobDetailPage() {
  const params = useParams<{ id: string }>();
  const { data: session } = useSession();
  const { data: job, error, isLoading } = useSWR<JobDetail>(
    session?.accessToken && session.workspaceId && params.id ? `/execution-jobs/${params.id}` : null,
    apiFetch,
    { refreshInterval: 4000 },
  );

  if (isLoading) {
    return <div className="min-h-screen bg-[#f9f7f3] p-8"><div className="mx-auto h-96 max-w-5xl animate-pulse rounded-[22px] bg-[#f3f0e8]" /></div>;
  }

  if (error || !job) {
    return <div className="min-h-screen bg-[#f9f7f3] p-8"><div className="mx-auto max-w-3xl rounded-[20px] border border-red-200 bg-red-50 p-8 text-red-800">Execution job could not be loaded.</div></div>;
  }

  return (
    <div className="min-h-screen bg-[#f9f7f3] text-[#202020]">
      <header className="border-b border-[rgba(32,32,32,0.12)]">
        <div className="mx-auto flex min-h-[68px] max-w-6xl items-center justify-between gap-4 px-4 sm:px-6 lg:px-8">
          <Link href={`/actions/${job.action_id}`} className="inline-flex items-center gap-3 text-sm font-semibold"><span className="grid h-9 w-9 place-items-center rounded-full bg-[#202020] text-white">←</span>Action detail</Link>
          <span className="rounded-full bg-[#202020] px-3 py-1.5 text-xs font-semibold capitalize text-white">{job.status.replaceAll("_", " ")}</span>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6 sm:py-10 lg:px-8 lg:py-12">
        <section className="rounded-[24px] bg-[#202020] p-6 text-white sm:p-8">
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-white/55">{job.adapter} adapter · {job.job_type}</p>
          <h1 className="mt-3 text-[clamp(2.4rem,6vw,4.2rem)] font-semibold leading-[0.96] tracking-[-0.055em]">Durable execution job</h1>
          <div className="mt-6 grid gap-3 sm:grid-cols-3">
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4"><p className="text-xs uppercase tracking-[0.12em] text-white/50">Attempts</p><p className="mt-2 text-2xl font-semibold">{job.attempt_count}/{job.max_attempts}</p></div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4"><p className="text-xs uppercase tracking-[0.12em] text-white/50">Lease owner</p><p className="mt-2 truncate text-sm font-semibold">{job.lease_owner || "Released"}</p></div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4"><p className="text-xs uppercase tracking-[0.12em] text-white/50">Created</p><p className="mt-2 text-sm font-semibold">{new Date(job.created_at).toLocaleString()}</p></div>
          </div>
        </section>

        {job.error_message && <section className="mt-5 rounded-[20px] border border-red-200 bg-red-50 p-5 text-red-800"><p className="font-semibold">{job.error_code || "Execution error"}</p><p className="mt-2 text-sm">{job.error_message}</p></section>}

        <section className="mt-8 grid gap-5 lg:grid-cols-2">
          {jsonPanel("Job payload", job.payload)}
          {jsonPanel("Job result", job.result)}
        </section>

        <section className="mt-8 rounded-[20px] border border-[rgba(32,32,32,0.12)] bg-white p-5 sm:p-6">
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#646464]">Attempts</p>
          <div className="mt-5 space-y-3">
            {job.attempts.length === 0 && <p className="text-sm text-[#646464]">No worker has claimed this job yet.</p>}
            {job.attempts.map((attempt) => <article key={attempt.id} className="rounded-2xl border border-[rgba(32,32,32,0.1)] bg-[#f9f7f3] p-4">
              <div className="flex flex-wrap items-center justify-between gap-3"><p className="font-semibold">Attempt {attempt.attempt_number}</p><span className="rounded-full bg-[#202020] px-2.5 py-1 text-[11px] font-semibold capitalize text-white">{attempt.status}</span></div>
              <p className="mt-2 text-xs text-[#8d8d8d]">{attempt.worker_id} · {new Date(attempt.started_at).toLocaleString()}</p>
              {attempt.error_message && <p className="mt-3 text-sm text-red-700">{attempt.error_code}: {attempt.error_message}</p>}
            </article>)}
          </div>
        </section>

        <section className="mt-8 rounded-[20px] border border-[rgba(32,32,32,0.12)] bg-white p-5 sm:p-6">
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#646464]">Immutable snapshots</p>
          <div className="mt-5 space-y-4">
            {job.snapshots.length === 0 && <p className="text-sm text-[#646464]">Snapshots appear when the worker captures execution state.</p>}
            {job.snapshots.map((snapshot) => <article key={snapshot.id} className="rounded-2xl border border-[rgba(32,32,32,0.1)] bg-[#f9f7f3] p-4 sm:p-5">
              <div className="flex flex-wrap items-center justify-between gap-3"><p className="font-semibold capitalize">{snapshot.snapshot_type} state</p><span className="font-mono text-[11px] text-[#8d8d8d]">{snapshot.checksum.slice(0, 16)}…</span></div>
              <p className="mt-1 text-xs text-[#8d8d8d]">{snapshot.external_revision || "No external revision"}</p>
              <pre className="mt-4 overflow-x-auto whitespace-pre-wrap text-xs leading-6 text-[#646464]">{JSON.stringify(snapshot.data, null, 2)}</pre>
            </article>)}
          </div>
        </section>
      </main>
    </div>
  );
}
