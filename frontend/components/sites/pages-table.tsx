"use client";

import { useState } from "react";
import useSWR from "swr";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function fetcher(url: string) {
  const res = await fetch(url);
  if (!res.ok) throw new Error("Failed to fetch");
  return res.json();
}

interface PagesTableProps {
  siteId: string;
}

interface PageItem {
  id: string;
  path: string;
  title: string | null;
  meta_description: string | null;
  h1: string | null;
  status_code: number | null;
  word_count: number | null;
  response_time_ms: number | null;
  meta: {
    internal_links_count?: number;
    external_links_count?: number;
    images_count?: number;
  } | null;
}

export default function PagesTable({ siteId }: PagesTableProps) {
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState("path");
  const [order, setOrder] = useState<"asc" | "desc">("asc");

  const { data, isLoading } = useSWR(
    `${API_URL}/sites/${siteId}/pages?page=${page}&limit=20&sort=${sort}&order=${order}`,
    fetcher
  );

  function handleSort(col: string) {
    if (sort === col) {
      setOrder(order === "asc" ? "desc" : "asc");
    } else {
      setSort(col);
      setOrder("asc");
    }
  }

  const sortIndicator = (col: string) =>
    sort === col ? (order === "asc" ? " ↑" : " ↓") : "";

  if (isLoading) {
    return <div className="h-48 bg-gray-200 rounded-lg animate-pulse" />;
  }

  if (!data || data.items.length === 0) {
    return (
      <div className="text-center py-8 text-gray-500">
        No pages crawled yet. Start a crawl to see results.
      </div>
    );
  }

  return (
    <div>
      <div className="flex justify-end mb-3">
        <a
          href={`${API_URL}/sites/${siteId}/export?format=csv`}
          download
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
        >
          📥 Export CSV
        </a>
      </div>
      <div className="overflow-x-auto bg-white rounded-lg border border-gray-200">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th
                onClick={() => handleSort("path")}
                className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase cursor-pointer hover:bg-gray-100"
              >
                URL{sortIndicator("path")}
              </th>
              <th
                onClick={() => handleSort("title")}
                className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase cursor-pointer hover:bg-gray-100"
              >
                Title{sortIndicator("title")}
              </th>
              <th
                onClick={() => handleSort("status_code")}
                className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase cursor-pointer hover:bg-gray-100"
              >
                Status{sortIndicator("status_code")}
              </th>
              <th
                onClick={() => handleSort("word_count")}
                className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase cursor-pointer hover:bg-gray-100"
              >
                Words{sortIndicator("word_count")}
              </th>
              <th
                onClick={() => handleSort("response_time_ms")}
                className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase cursor-pointer hover:bg-gray-100"
              >
                Response{sortIndicator("response_time_ms")}
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                H1
              </th>
              <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase">
                Int Links
              </th>
              <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase">
                Ext Links
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {data.items.map((p: PageItem) => (
              <tr key={p.id} className="hover:bg-gray-50">
                <td className="px-4 py-3 text-sm text-gray-900 max-w-xs truncate">
                  {p.path}
                </td>
                <td className="px-4 py-3 text-sm text-gray-600 max-w-xs truncate">
                  {p.title || "—"}
                </td>
                <td className="px-4 py-3 text-sm">
                  <span
                    className={
                      p.status_code === 200
                        ? "text-green-600"
                        : p.status_code && p.status_code >= 400
                          ? "text-red-600"
                          : "text-gray-600"
                    }
                  >
                    {p.status_code || "—"}
                  </span>
                </td>
                <td className="px-4 py-3 text-sm text-gray-600">
                  {p.word_count?.toLocaleString() || "—"}
                </td>
                <td className="px-4 py-3 text-sm text-gray-600">
                  {p.response_time_ms ? `${p.response_time_ms}ms` : "—"}
                </td>
                <td className="px-4 py-3 text-sm text-gray-600 max-w-50 truncate">
                  {p.h1 || "—"}
                </td>
                <td className="px-4 py-3 text-sm text-center text-gray-600">
                  {p.meta?.internal_links_count ?? "—"}
                </td>
                <td className="px-4 py-3 text-sm text-center text-gray-600">
                  {p.meta?.external_links_count ?? "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {data.pages > 1 && (
        <div className="flex items-center justify-between mt-4">
          <p className="text-sm text-gray-600">
            Page {data.page} of {data.pages} ({data.total} total)
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
              disabled={page >= data.pages}
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
