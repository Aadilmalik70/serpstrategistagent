"use client";

import Link from "next/link";
import { signOut, useSession } from "next-auth/react";
import useSWR from "swr";

import EmptyState from "@/components/dashboard/empty-state";
import SiteCard from "@/components/dashboard/site-card";
import WorkspaceSwitcher from "@/components/workspaces/workspace-switcher";
import { apiFetch } from "@/lib/api";

type SiteSummary = {
  id: string;
  domain: string;
  name: string;
  status: string;
};

export default function Dashboard() {
  const { data: session, status } = useSession();
  const canUseApi = Boolean(session?.accessToken && session.workspaceId);
  const { data: sites, error, isLoading } = useSWR<SiteSummary[]>(
    canUseApi ? "/sites" : null,
    apiFetch,
  );

  const activeSites = sites?.filter((site) => site.status === "active").length ?? 0;
  const crawlingSites = sites?.filter((site) => site.status === "crawling").length ?? 0;

  async function handleSignOut() {
    await signOut({ redirect: false });
    window.location.assign("/login");
  }

  return (
    <div className="min-h-screen bg-[#f9f7f3] text-[#202020]">
      <header className="border-b border-[rgba(32,32,32,0.12)] bg-[#f9f7f3]">
        <div className="mx-auto flex min-h-[68px] max-w-7xl flex-col gap-3 px-4 py-3 sm:px-6 md:flex-row md:items-center md:justify-between md:py-0 lg:px-8">
          <div className="flex items-center gap-3">
            <span className="grid h-10 w-10 place-items-center rounded-full bg-[#ea2804] text-sm font-bold text-white">S</span>
            <div>
              <p className="font-semibold tracking-[-0.02em]">SERP Strategists</p>
              <p className="text-xs text-[#646464]">Growth operator console</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <WorkspaceSwitcher />
            <button
              onClick={handleSignOut}
              className="min-h-10 rounded-full px-3 text-sm font-semibold text-[#646464] transition hover:bg-[#f3f0e8] hover:text-[#202020]"
            >
              Sign out
            </button>
          </div>
        </div>
      </header>

      <section className="operator-grid border-b border-[rgba(32,32,32,0.12)] bg-[#f3f0e8]">
        <div className="mx-auto max-w-7xl px-4 py-10 sm:px-6 sm:py-14 lg:px-8">
          <div className="flex flex-col gap-8 lg:flex-row lg:items-end lg:justify-between">
            <div className="max-w-3xl">
              <div className="inline-flex items-center gap-2 rounded-full border border-[rgba(32,32,32,0.12)] bg-white px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.14em] text-[#575757]">
                <span className="h-2 w-2 rounded-full bg-[#2b9a66]" />
                Operator online
              </div>
              <h1 className="mt-5 text-[clamp(2.6rem,7vw,5rem)] font-semibold leading-[0.95] tracking-[-0.06em] text-[#202020]">
                Observe. Prioritize. Ship growth.
              </h1>
              <p className="mt-5 max-w-2xl text-base leading-7 text-[#575757] sm:text-lg">
                Your governed search workspace for technical SEO, GEO visibility and measurable execution.
              </p>
            </div>

            {canUseApi && session?.workspaceRole !== "member" && (
              <Link
                href="/sites/new"
                className="inline-flex min-h-12 items-center justify-center rounded-full bg-[#ea2804] px-6 text-sm font-semibold text-white transition hover:bg-[#c01f00]"
              >
                Add a site
              </Link>
            )}
          </div>
        </div>
      </section>

      <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6 sm:py-10 lg:px-8 lg:py-12">
        {status === "loading" && (
          <div className="h-32 animate-pulse rounded-[18px] bg-[#f3f0e8]" />
        )}

        {status !== "loading" && session?.legacy && (
          <div className="rounded-[18px] border border-amber-300 bg-amber-50 p-5 text-amber-900 sm:p-6">
            <h3 className="font-semibold">Temporary admin session</h3>
            <p className="mt-1 text-sm leading-6">
              Tenant APIs require a registered account. Sign out and create an account to continue.
            </p>
            <Link href="/register" className="mt-4 inline-flex min-h-10 items-center rounded-full bg-[#202020] px-4 text-sm font-semibold text-white">
              Create registered account
            </Link>
          </div>
        )}

        {canUseApi && (
          <section className="grid gap-4 sm:grid-cols-3">
            <div className="rounded-[18px] border border-[rgba(32,32,32,0.12)] bg-white p-5 sm:p-6">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#646464]">Workspace</p>
              <p className="mt-3 truncate text-2xl font-semibold tracking-[-0.04em]">{session?.workspaceName || "Active workspace"}</p>
              <p className="mt-1 text-sm capitalize text-[#646464]">{session?.workspaceRole}</p>
            </div>
            <div className="rounded-[18px] border border-[rgba(32,32,32,0.12)] bg-white p-5 sm:p-6">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#646464]">Active sites</p>
              <p className="mt-3 text-3xl font-semibold tracking-[-0.04em]">{sites ? activeSites : "—"}</p>
              <p className="mt-1 text-sm text-[#646464]">Ready for operator actions</p>
            </div>
            <div className="rounded-[18px] border border-[rgba(32,32,32,0.12)] bg-white p-5 sm:p-6">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#646464]">Crawling</p>
              <p className="mt-3 text-3xl font-semibold tracking-[-0.04em]">{sites ? crawlingSites : "—"}</p>
              <p className="mt-1 text-sm text-[#646464]">Live discovery jobs</p>
            </div>
          </section>
        )}

        <section className="mt-8">
          <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#646464]">Portfolio</p>
              <h2 className="mt-2 text-3xl font-semibold tracking-[-0.045em] text-[#202020]">Sites in this workspace</h2>
            </div>
            {canUseApi && session?.workspaceRole !== "member" && (
              <Link href="/sites/new" className="text-sm font-semibold text-[#ea2804] hover:text-[#c01f00]">
                Add another site →
              </Link>
            )}
          </div>

          {canUseApi && isLoading && (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
              {[1, 2, 3].map((item) => (
                <div key={item} className="h-56 animate-pulse rounded-[18px] bg-[#f3f0e8]" />
              ))}
            </div>
          )}

          {canUseApi && error && (
            <div className="rounded-[18px] border border-red-200 bg-red-50 px-5 py-10 text-center">
              <p className="font-semibold text-red-800">Failed to load workspace sites</p>
              <button
                onClick={() => window.location.reload()}
                className="mt-4 min-h-10 rounded-full bg-[#202020] px-4 text-sm font-semibold text-white"
              >
                Retry
              </button>
            </div>
          )}

          {canUseApi && !isLoading && !error && sites?.length === 0 && <EmptyState />}

          {canUseApi && !isLoading && !error && Boolean(sites?.length) && (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
              {sites?.map((site) => <SiteCard key={site.id} site={site} />)}
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
