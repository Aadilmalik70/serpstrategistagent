"use client";

import Link from "next/link";
import { useSession } from "next-auth/react";
import useSWR from "swr";

import { apiFetch } from "@/lib/api";

type LinkedProvider = {
  provider: string;
  email: string;
  linked_at: string;
  last_login_at: string;
};

type IntegrationSummary = {
  id: string;
  provider: string;
  status: string;
};

export default function SettingsPage() {
  const { data: session } = useSession();
  const { data: providers } = useSWR<LinkedProvider[]>(
    session?.accessToken ? "/auth/providers" : null,
    apiFetch,
  );
  const { data: integrations } = useSWR<IntegrationSummary[]>(
    session?.accessToken && session.workspaceId ? "/integrations" : null,
    apiFetch,
  );

  return (
    <div className="min-h-screen bg-[#f9f7f3] text-[#202020]">
      <header className="border-b border-[rgba(32,32,32,0.12)] bg-[#f9f7f3]">
        <div className="mx-auto flex min-h-[68px] max-w-6xl items-center justify-between gap-4 px-4 sm:px-6 lg:px-8">
          <Link href="/" className="inline-flex items-center gap-3 text-sm font-semibold">
            <span className="grid h-9 w-9 place-items-center rounded-full bg-[#202020] text-white">←</span>
            Back to operator
          </Link>
          <span className="max-w-[12rem] truncate text-sm text-[#646464] sm:max-w-none">
            {session?.user?.email}
          </span>
        </div>
      </header>

      <section className="operator-grid border-b border-[rgba(32,32,32,0.12)] bg-[#f3f0e8]">
        <div className="mx-auto max-w-6xl px-4 py-12 sm:px-6 sm:py-16 lg:px-8">
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#646464]">Control center</p>
          <h1 className="mt-3 text-[clamp(2.6rem,7vw,4.8rem)] font-semibold leading-[0.96] tracking-[-0.055em]">
            Settings without hidden state.
          </h1>
          <p className="mt-5 max-w-2xl text-base leading-7 text-[#575757] sm:text-lg">
            Manage workspace boundaries, provider access and the identity used to approve operator actions.
          </p>
        </div>
      </section>

      <main className="mx-auto max-w-6xl space-y-8 px-4 py-8 sm:px-6 sm:py-10 lg:px-8 lg:py-12">
        <section className="grid gap-5 md:grid-cols-2">
          <Link
            href="/settings/workspace"
            className="group rounded-[20px] border border-[rgba(32,32,32,0.12)] bg-white p-6 transition hover:-translate-y-0.5 hover:border-[rgba(32,32,32,0.28)] sm:p-8"
          >
            <div className="grid h-12 w-12 place-items-center rounded-full bg-[#202020] text-white">W</div>
            <p className="mt-7 text-xs font-semibold uppercase tracking-[0.16em] text-[#646464]">Tenancy</p>
            <h2 className="mt-2 text-3xl font-semibold tracking-[-0.045em]">Workspace & team</h2>
            <p className="mt-3 max-w-md text-sm leading-6 text-[#646464]">
              Switch client environments, invite teammates and control owner, admin and member permissions.
            </p>
            <span className="mt-7 inline-flex items-center gap-2 text-sm font-semibold text-[#ea2804]">
              Manage workspace <span className="transition group-hover:translate-x-1">→</span>
            </span>
          </Link>

          <Link
            href="/settings/integrations"
            className="group rounded-[20px] border border-[rgba(32,32,32,0.12)] bg-[#202020] p-6 text-white transition hover:-translate-y-0.5 sm:p-8"
          >
            <div className="grid h-12 w-12 place-items-center rounded-full bg-[#ea2804] text-white">↗</div>
            <p className="mt-7 text-xs font-semibold uppercase tracking-[0.16em] text-white/55">Connections</p>
            <h2 className="mt-2 text-3xl font-semibold tracking-[-0.045em]">Integrations</h2>
            <p className="mt-3 max-w-md text-sm leading-6 text-white/65">
              Add encrypted provider credentials, test connections, rotate keys and revoke access.
            </p>
            <div className="mt-7 flex items-center justify-between gap-4">
              <span className="text-sm font-semibold text-[#ff6a4d]">Manage integrations →</span>
              <span className="rounded-full border border-white/15 px-3 py-1.5 text-xs text-white/70">
                {integrations?.length ?? "—"} active
              </span>
            </div>
          </Link>
        </section>

        <section className="rounded-[20px] border border-[rgba(32,32,32,0.12)] bg-white p-6 sm:p-8">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#646464]">Identity</p>
              <h2 className="mt-2 text-2xl font-semibold tracking-[-0.035em]">Linked sign-in providers</h2>
              <p className="mt-1 text-sm text-[#646464]">Provider tokens remain server-side and are never returned to the browser session.</p>
            </div>
            <span className="rounded-full bg-[#f3f0e8] px-3 py-1.5 text-xs font-semibold text-[#575757]">
              {providers?.length ?? "—"} linked
            </span>
          </div>

          <div className="mt-6 grid gap-3 sm:grid-cols-2">
            {!providers && [1, 2].map((item) => (
              <div key={item} className="h-24 animate-pulse rounded-2xl bg-[#f3f0e8]" />
            ))}
            {providers?.length === 0 && (
              <div className="rounded-2xl border border-dashed border-[rgba(32,32,32,0.2)] p-5 text-sm text-[#646464] sm:col-span-2">
                No social provider is linked. Email and password sign-in remains available.
              </div>
            )}
            {providers?.map((provider) => (
              <article key={`${provider.provider}-${provider.email}`} className="rounded-2xl border border-[rgba(32,32,32,0.1)] bg-[#f9f7f3] p-5">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="font-semibold capitalize">{provider.provider}</p>
                    <p className="mt-1 break-all text-sm text-[#646464]">{provider.email}</p>
                  </div>
                  <span className="rounded-full bg-[#2b9a66] px-2.5 py-1 text-[11px] font-semibold text-white">Linked</span>
                </div>
                <p className="mt-4 text-xs text-[#8d8d8d]">
                  Last used {new Date(provider.last_login_at).toLocaleDateString()}
                </p>
              </article>
            ))}
          </div>
        </section>
      </main>
    </div>
  );
}
