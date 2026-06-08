"use client";

import { useState } from "react";
import useSWR from "swr";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function fetcher(url: string) {
  const res = await fetch(url);
  if (!res.ok) throw new Error("Failed to fetch");
  return res.json();
}

interface LinksProps {
  siteId: string;
}

interface LinkItem {
  id: string;
  path: string;
  title: string | null;
  internal_links_count: number;
  external_links_count: number;
  inlinks_count: number;
  linked_from: string[];
}

export default function LinksPanel({ siteId }: LinksProps) {
  const [page, setPage] = useState(1);
  const { data, isLoading } = useSWR(
    `${API_URL}/sites/${siteId}/links?page=${page}&limit=30`,
    fetcher
  );

  if (isLoading) {
    return <div className="h-48 bg-gray-200 rounded-lg animate-pulse" />;
  }

  if (!data || data.items.length === 0) {
    return (
      <div className="text-center py-12 text-gray-500">
        No link data available. Run a crawl first.
      </div>
    );
  }

  const items: LinkItem[] = data.items;
  const totalPages = Math.ceil(data.total / 30);

  // Stats
  const totalInternalLinks = items.reduce((s, i) => s + i.internal_links_count, 0);
  const totalExternalLinks = items.reduce((s, i) => s + i.external_links_count, 0);
  const orphanPages = items.filter((i) => i.inlinks_count === 0);

  return (
    <div className="space-y-4">
      {/* Stats bar */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
        <div className="bg-white rounded-lg border border-gray-200 p-4 text-center">
          <p className="text-xs text-gray-500">Total Internal Links</p>
          <p className="text-xl font-bold">{totalInternalLinks}</p>
        </div>
        <div className="bg-white rounded-lg border border-gray-200 p-4 text-center">
          <p className="text-xs text-gray-500">Total External Links</p>
          <p className="text-xl font-bold">{totalExternalLinks}</p>
        </div>
        <div className="bg-white rounded-lg border border-gray-200 p-4 text-center">
          <p className="text-xs text-gray-500">Orphan Pages</p>
          <p className="text-xl font-bold text-red-600">{orphanPages.length}</p>
        </div>
        <div className="bg-white rounded-lg border border-gray-200 p-4 text-center">
          <p className="text-xs text-gray-500">Avg Internal Links/Page</p>
          <p className="text-xl font-bold">
            {items.length ? Math.round(totalInternalLinks / items.length) : 0}
          </p>
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto bg-white rounded-lg border border-gray-200">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                Page
              </th>
              <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase">
                Outgoing (Int)
              </th>
              <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase">
                Outgoing (Ext)
              </th>
              <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase">
                Incoming
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {items.map((item) => (
              <tr key={item.id} className="hover:bg-gray-50">
                <td className="px-4 py-3 text-sm">
                  <div className="font-medium text-gray-900 truncate max-w-sm">
                    {item.path}
                  </div>
                  {item.title && (
                    <div className="text-xs text-gray-400 truncate max-w-sm">
                      {item.title}
                    </div>
                  )}
                </td>
                <td className="px-4 py-3 text-sm text-center text-gray-600">
                  {item.internal_links_count}
                </td>
                <td className="px-4 py-3 text-sm text-center text-gray-600">
                  {item.external_links_count}
                </td>
                <td className="px-4 py-3 text-sm text-center">
                  <span
                    className={
                      item.inlinks_count === 0
                        ? "text-red-600 font-medium"
                        : "text-gray-600"
                    }
                  >
                    {item.inlinks_count}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between">
          <p className="text-sm text-gray-600">
            Page {page} of {totalPages} ({data.total} pages)
          </p>
          <div className="flex gap-2">
            <button
              disabled={page <= 1}
              onClick={() => setPage(page - 1)}
              className="px-3 py-1 text-sm border rounded disabled:opacity-50"
            >
              Previous
            </button>
            <button
              disabled={page >= totalPages}
              onClick={() => setPage(page + 1)}
              className="px-3 py-1 text-sm border rounded disabled:opacity-50"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
