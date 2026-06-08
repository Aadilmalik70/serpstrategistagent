"use client";

import useSWR from "swr";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function fetcher(url: string) {
  const res = await fetch(url);
  if (!res.ok) throw new Error("Failed to fetch");
  return res.json();
}

interface StatusCodesProps {
  siteId: string;
}

interface StatusEntry {
  status_code: number;
  count: number;
  percentage: number;
}

function statusColor(code: number): string {
  if (code >= 200 && code < 300) return "bg-green-100 text-green-800";
  if (code >= 300 && code < 400) return "bg-yellow-100 text-yellow-800";
  if (code >= 400 && code < 500) return "bg-red-100 text-red-800";
  if (code >= 500) return "bg-red-200 text-red-900";
  return "bg-gray-100 text-gray-800";
}

function statusBarColor(code: number): string {
  if (code >= 200 && code < 300) return "#10b981";
  if (code >= 300 && code < 400) return "#f59e0b";
  if (code >= 400 && code < 500) return "#ef4444";
  if (code >= 500) return "#991b1b";
  return "#6b7280";
}

export default function StatusCodesPanel({ siteId }: StatusCodesProps) {
  const { data, isLoading } = useSWR<StatusEntry[]>(
    `${API_URL}/sites/${siteId}/status-codes`,
    fetcher
  );

  if (isLoading) {
    return <div className="h-32 bg-gray-200 rounded-lg animate-pulse" />;
  }

  if (!data || data.length === 0) {
    return (
      <div className="text-center py-8 text-gray-500">
        No status code data available.
      </div>
    );
  }

  const total = data.reduce((s, d) => s + d.count, 0);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold">Status Codes</h3>
        <span className="text-sm text-gray-500">{total} pages total</span>
      </div>

      {/* Status bar overview */}
      <div className="w-full h-4 rounded-full overflow-hidden flex">
        {data.map((entry) => (
          <div
            key={entry.status_code}
            style={{
              width: `${entry.percentage}%`,
              backgroundColor: statusBarColor(entry.status_code),
            }}
            title={`${entry.status_code}: ${entry.count} (${entry.percentage}%)`}
          />
        ))}
      </div>

      {/* Detail list */}
      <div className="space-y-2">
        {data.map((entry) => (
          <div
            key={entry.status_code}
            className="flex items-center justify-between bg-white rounded-lg border border-gray-200 px-4 py-3"
          >
            <div className="flex items-center gap-3">
              <span
                className={`px-2 py-0.5 rounded text-sm font-mono font-medium ${statusColor(
                  entry.status_code
                )}`}
              >
                {entry.status_code}
              </span>
              <span className="text-sm text-gray-600">
                {entry.status_code === 200 && "OK"}
                {entry.status_code === 301 && "Moved Permanently"}
                {entry.status_code === 302 && "Found (Redirect)"}
                {entry.status_code === 404 && "Not Found"}
                {entry.status_code === 500 && "Internal Server Error"}
                {entry.status_code === 503 && "Service Unavailable"}
              </span>
            </div>
            <div className="flex items-center gap-4">
              <span className="text-sm font-medium">{entry.count} pages</span>
              <span className="text-sm text-gray-500">
                {entry.percentage.toFixed(1)}%
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
