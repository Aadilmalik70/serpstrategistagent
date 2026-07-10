"use client";

import { useState } from "react";
import useSWR from "swr";

import { apiDownload, apiFetch } from "@/lib/api";

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

interface PagesResponse {
  items: PageItem[];
  total: number;
  page: number;
  pages: number;
}

export default function PagesTable({ siteId }: PagesTableProps) {
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState("path");
  const [order, setOrder] = useState<"asc" | "desc">("asc");
  const [exporting, setExporting] = useState(false);

  const { data, isLoading } = useSWR<PagesResponse>(
    `/sites/${siteId}/pages?page=${page}&limit=20&sort=${sort}&order=${order}`,
    apiFetch,
  );

  function handleSort(column: string) {
    if (sort === column) {
      setOrder(order === "asc" ? "desc" : "asc");
    } else {
      setSort(column);
      setOrder("asc");
    }
  }

  async function handleExport() {
    setExporting(true);
    try {
      const blob = await apiDownload(`/sites/${siteId}/export?format=csv`);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "crawl-export.csv";
      anchor.click();
      URL.revokeObjectURL(url);
    } finally {
      setExporting(false);
    }
  }

  const sortIndicator = (column: string) =>
    sort === column ? (order === "asc" ? " ↑" : " ↓") : "";

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
        <button
          type="button"
          onClick={handleExport}
          disabled={exporting}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 disabled:opacity-50"
        >
          {exporting ? "Exporting..." : "📥 Export CSV"}
        </button>
      </div>
      <div className="overflow-x-auto bg-white rounded-lg border border-gray-200">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              {[
                ["path", "URL"],
                ["title", "Title"],
                ["status_code", "Status"],
                ["word_count", "Words"],
                ["response_time_ms", "Response"],
              ].map(([column, label]) => (
                <th
                  key={column}
                  onClick={() => handleSort(column)}
                  className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase cursor-pointer hover:bg-gray-100"
                >
                  {label}{sortIndicator(column)}
                </th>
              ))}
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">H1</th>
              <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase">Int Links</th>
              <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase">Ext Links</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {data.items.map((item) => (
              <tr key={item.id} className="hover:bg-gray-50">
                <td className="px-4 py-3 text-sm text-gray-900 max-w-xs truncate">{item.path}</td>
                <td className="px-4 py-3 text-sm text-gray-600 max-w-xs truncate">{item.title || "—"}</td>
                <td className="px-4 py-3 text-sm">
                  <span
                    className={
                      item.status_code === 200
                        ? "text-green-600"
                        : item.status_code && item.status_code >= 400
                          ? "text-red-600"
                          : "text-gray-600"
                    }
                  >
                    {item.status_code || "—"}
                  </span>
                </td>
                <td className="px-4 py-3 text-sm text-gray-600">{item.word_count?.toLocaleString() || "—"}</td>
                <td className="px-4 py-3 text-sm text-gray-600">{item.response_time_ms ? `${item.response_time_ms}ms` : "—"}</td>
                <td className="px-4 py-3 text-sm text-gray-600 max-w-50 truncate">{item.h1 || "—"}</td>
                <td className="px-4 py-3 text-sm text-center text-gray-600">{item.meta?.internal_links_count ?? "—"}</td>
                <td className="px-4 py-3 text-sm text-center text-gray-600">{item.meta?.external_links_count ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

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
