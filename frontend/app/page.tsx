"use client";

import { useSession, signOut } from "next-auth/react";
import useSWR from "swr";
import SiteCard from "@/components/dashboard/site-card";
import EmptyState from "@/components/dashboard/empty-state";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function fetcher(url: string) {
  const res = await fetch(url);
  if (!res.ok) throw new Error("Failed to fetch");
  return res.json();
}

export default function Dashboard() {
  const { data: session } = useSession();
  const { data: sites, error, isLoading } = useSWR(`${API_URL}/sites`, fetcher);

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <h1 className="text-xl font-bold">SERP Strategist Agent</h1>
          <div className="flex items-center gap-4">
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

      {/* Main content */}
      <main className="max-w-7xl mx-auto px-6 py-8">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-2xl font-semibold">Your Sites</h2>
          <a
            href="/sites/new"
            className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 text-sm font-medium"
          >
            Add Site
          </a>
        </div>

        {/* Loading state */}
        {isLoading && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-32 bg-gray-200 rounded-lg animate-pulse" />
            ))}
          </div>
        )}

        {/* Error state */}
        {error && (
          <div className="text-center py-12">
            <p className="text-red-600 mb-2">Failed to load sites</p>
            <button
              onClick={() => window.location.reload()}
              className="text-blue-600 hover:underline text-sm"
            >
              Retry
            </button>
          </div>
        )}

        {/* Empty state */}
        {!isLoading && !error && sites?.length === 0 && <EmptyState />}

        {/* Sites grid */}
        {!isLoading && !error && sites?.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {sites.map((site: { id: string; domain: string; name: string; status: string }) => (
              <SiteCard key={site.id} site={site} />
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
