"use client";

import useSWR from "swr";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function fetcher(url: string) {
  const res = await fetch(url);
  if (!res.ok) throw new Error("Failed to fetch");
  return res.json();
}

interface Issue {
  id: string;
  category: string;
  severity: string;
  title: string;
  description: string;
  recommendation: string | null;
  affected_url: string | null;
  status: string;
  created_at: string;
}

const severityColors: Record<string, string> = {
  critical: "bg-red-100 text-red-800",
  high: "bg-orange-100 text-orange-800",
  medium: "bg-yellow-100 text-yellow-800",
  low: "bg-blue-100 text-blue-800",
};

const categoryIcons: Record<string, string> = {
  technical: "🔧",
  content: "📝",
  opportunity: "💡",
};

export default function IssuesPanel({ siteId }: { siteId: string }) {
  const { data: issues, error, mutate } = useSWR<Issue[]>(
    `${API_URL}/agent/issues/${siteId}?status=all`,
    fetcher
  );

  if (error) return null;
  if (!issues) {
    return (
      <div className="animate-pulse space-y-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-20 bg-gray-200 rounded" />
        ))}
      </div>
    );
  }

  if (issues.length === 0) {
    return (
      <div className="text-center py-12 text-gray-500">
        <p className="text-lg font-medium">No issues found</p>
        <p className="text-sm mt-1">
          Click &quot;Run Agent&quot; to analyze your site for SEO issues.
        </p>
      </div>
    );
  }

  async function dismissIssue(issueId: string) {
    await fetch(`${API_URL}/agent/issues/${issueId}?status=dismissed`, {
      method: "PATCH",
    });
    mutate();
  }

  const openIssues = issues.filter((i) => i.status === "open");
  const dismissedIssues = issues.filter((i) => i.status !== "open");

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold">
          Issues ({openIssues.length} open)
        </h3>
        <div className="flex gap-2 text-xs">
          <span className="px-2 py-1 rounded bg-red-100 text-red-800">
            {issues.filter((i) => i.severity === "critical" && i.status === "open").length} critical
          </span>
          <span className="px-2 py-1 rounded bg-orange-100 text-orange-800">
            {issues.filter((i) => i.severity === "high" && i.status === "open").length} high
          </span>
          <span className="px-2 py-1 rounded bg-yellow-100 text-yellow-800">
            {issues.filter((i) => i.severity === "medium" && i.status === "open").length} medium
          </span>
        </div>
      </div>

      {openIssues.map((issue) => (
        <div
          key={issue.id}
          className="border border-gray-200 rounded-lg p-4 bg-white"
        >
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-2">
              <span>{categoryIcons[issue.category] || "📋"}</span>
              <span
                className={`text-xs px-2 py-0.5 rounded font-medium ${
                  severityColors[issue.severity] || "bg-gray-100 text-gray-800"
                }`}
              >
                {issue.severity}
              </span>
              <h4 className="font-medium text-sm">{issue.title}</h4>
            </div>
            <button
              onClick={() => dismissIssue(issue.id)}
              className="text-xs text-gray-400 hover:text-gray-600"
            >
              Dismiss
            </button>
          </div>
          {issue.affected_url && (
            <p className="text-xs text-gray-400 mt-1 font-mono">
              {issue.affected_url}
            </p>
          )}
          <p className="text-sm text-gray-600 mt-2">{issue.description}</p>
          {issue.recommendation && (
            <p className="text-sm text-green-700 mt-2 bg-green-50 p-2 rounded">
              💡 {issue.recommendation}
            </p>
          )}
        </div>
      ))}

      {dismissedIssues.length > 0 && (
        <details className="text-sm text-gray-500">
          <summary className="cursor-pointer hover:text-gray-700">
            {dismissedIssues.length} dismissed issues
          </summary>
          <div className="mt-2 space-y-2">
            {dismissedIssues.map((issue) => (
              <div
                key={issue.id}
                className="border border-gray-100 rounded p-3 bg-gray-50 opacity-60"
              >
                <span className="text-xs">{issue.title}</span>
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}
