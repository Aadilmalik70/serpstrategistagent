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

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="border-b border-gray-200 bg-white px-6 py-4">
        <div className="mx-auto flex max-w-7xl flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div>
            <h1 className="text-xl font-bold">SERP Strategist Agent</h1>
            {session?.workspaceName && (
              <p className="text-xs text-gray-500">
                {session.workspaceName} · {session.workspaceRole}
              </p>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-4">
            <WorkspaceSwitcher />
            <span className="text-sm text-gray-600">{session?.user?.email}</span>
            <button
              onClick={() => signOut()}
              className="text-sm text-gray-500 hover:text-gray-700"
            >
              Sign Out
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-6 py-8">
        <div className="mb-6 flex items-center justify-between">
          <h2 className="text-2xl font-semibold">Your Sites</h2>
          {canUseApi && session?.workspaceRole !== "member" && (
            <Link
              href="/sites/new"
              className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
            >
              Add Site
            </Link>
          )}
        </div>

        {status === "loading" && (
          <div className="h-32 animate-pulse rounded-lg bg-gray-200" />
        )}

        {status !== "loading" && session?.legacy && (
          <div className="rounded-lg border border-amber-300 bg-amber-50 p-5 text-amber-900">
            <h3 className="font-semibold">Temporary admin session</h3>
            <p className="mt-1 text-sm">
              Tenant APIs require a registered account. Sign out and create an account to continue.
            </p>
            <Link href="/register" className="mt-3 inline-block text-sm font-medium underline">
              Create registered account
            </Link>
          </div>
        )}

        {canUseApi && isLoading && (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
            {[1, 2, 3].map((item) => (
              <div key={item} className="h-32 animate-pulse rounded-lg bg-gray-200" />
            ))}
          </div>
        )}

        {canUseApi && error && (
          <div className="py-12 text-center">
            <p className="mb-2 text-red-600">Failed to load workspace sites</p>
            <button
              onClick={() => window.location.reload()}
              className="text-sm text-blue-600 hover:underline"
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
      </main>
    </div>
  );
}
