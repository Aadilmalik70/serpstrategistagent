"use client";

import { useState } from "react";
import useSWR from "swr";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function fetcher(url: string) {
  const res = await fetch(url);
  if (!res.ok) throw new Error("Failed to fetch");
  return res.json();
}

interface FixAction {
  id: string;
  site_id: string;
  issue_id: string;
  action_type: string;
  status: string;
  title: string;
  description: string | null;
  fix_content: Record<string, unknown> | null;
  target_path: string | null;
  execution_result: Record<string, unknown> | null;
  created_at: string;
  approved_at: string | null;
  executed_at: string | null;
}

const statusColors: Record<string, string> = {
  pending: "bg-yellow-100 text-yellow-800",
  approved: "bg-blue-100 text-blue-800",
  executing: "bg-purple-100 text-purple-800",
  completed: "bg-green-100 text-green-800",
  rejected: "bg-gray-100 text-gray-500",
  failed: "bg-red-100 text-red-800",
};

const actionTypeIcons: Record<string, string> = {
  github_pr: "🔀",
  wordpress_update: "📝",
  recommendation: "💡",
};

export default function FixActionsPanel({ siteId }: { siteId: string }) {
  const { data: fixes, error, mutate } = useSWR<FixAction[]>(
    `${API_URL}/actions/fixes/${siteId}`,
    fetcher
  );
  const [generating, setGenerating] = useState(false);
  const [executing, setExecuting] = useState<string | null>(null);

  if (error) return null;
  if (!fixes) {
    return (
      <div className="animate-pulse space-y-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-20 bg-gray-200 rounded" />
        ))}
      </div>
    );
  }

  async function generateFixPlans() {
    setGenerating(true);
    try {
      await fetch(`${API_URL}/actions/fix-plan-bulk/${siteId}?max_issues=10`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      mutate();
    } finally {
      setGenerating(false);
    }
  }

  async function approveAction(fixId: string) {
    await fetch(`${API_URL}/actions/fix/${fixId}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "approve" }),
    });
    mutate();
  }

  async function rejectAction(fixId: string) {
    await fetch(`${API_URL}/actions/fix/${fixId}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "reject" }),
    });
    mutate();
  }

  async function executeAction(fixId: string) {
    setExecuting(fixId);
    try {
      await fetch(`${API_URL}/actions/fix/${fixId}/execute`, {
        method: "POST",
      });
      mutate();
    } finally {
      setExecuting(null);
    }
  }

  async function approveAndExecute(fixId: string) {
    setExecuting(fixId);
    try {
      await fetch(`${API_URL}/actions/approve-and-execute/${fixId}`, {
        method: "POST",
      });
      mutate();
    } finally {
      setExecuting(null);
    }
  }

  const pending = fixes.filter((f) => f.status === "pending");
  const approved = fixes.filter((f) => f.status === "approved");
  const completed = fixes.filter((f) => f.status === "completed");
  const failed = fixes.filter((f) => f.status === "failed" || f.status === "rejected");

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold">
          Fix Actions ({fixes.length})
        </h3>
        <button
          onClick={generateFixPlans}
          disabled={generating}
          className={`px-4 py-2 rounded-md text-sm font-medium ${
            generating
              ? "bg-gray-100 text-gray-400 cursor-not-allowed"
              : "bg-blue-600 text-white hover:bg-blue-700"
          }`}
        >
          {generating ? "Generating..." : "Generate Fix Plans"}
        </button>
      </div>

      {/* Status summary */}
      {fixes.length > 0 && (
        <div className="flex gap-2 text-xs">
          <span className="px-2 py-1 rounded bg-yellow-100 text-yellow-800">
            {pending.length} pending
          </span>
          <span className="px-2 py-1 rounded bg-blue-100 text-blue-800">
            {approved.length} approved
          </span>
          <span className="px-2 py-1 rounded bg-green-100 text-green-800">
            {completed.length} completed
          </span>
          {failed.length > 0 && (
            <span className="px-2 py-1 rounded bg-red-100 text-red-800">
              {failed.length} failed/rejected
            </span>
          )}
        </div>
      )}

      {/* Empty state */}
      {fixes.length === 0 && (
        <div className="text-center py-12 text-gray-500">
          <p className="text-lg font-medium">No fix plans yet</p>
          <p className="text-sm mt-1">
            Click &quot;Generate Fix Plans&quot; to create automated fixes for your SEO issues.
          </p>
        </div>
      )}

      {/* Pending actions */}
      {pending.length > 0 && (
        <div className="space-y-3">
          <h4 className="text-sm font-medium text-gray-700">⏳ Pending Approval</h4>
          {pending.map((fix) => (
            <FixCard
              key={fix.id}
              fix={fix}
              onApprove={() => approveAction(fix.id)}
              onReject={() => rejectAction(fix.id)}
              onApproveAndExecute={() => approveAndExecute(fix.id)}
              executing={executing === fix.id}
            />
          ))}
        </div>
      )}

      {/* Approved (ready to execute) */}
      {approved.length > 0 && (
        <div className="space-y-3">
          <h4 className="text-sm font-medium text-gray-700">✅ Approved — Ready to Execute</h4>
          {approved.map((fix) => (
            <FixCard
              key={fix.id}
              fix={fix}
              onExecute={() => executeAction(fix.id)}
              executing={executing === fix.id}
            />
          ))}
        </div>
      )}

      {/* Completed */}
      {completed.length > 0 && (
        <div className="space-y-3">
          <h4 className="text-sm font-medium text-gray-700">🎉 Completed</h4>
          {completed.map((fix) => (
            <FixCard key={fix.id} fix={fix} />
          ))}
        </div>
      )}

      {/* Failed/Rejected */}
      {failed.length > 0 && (
        <details className="text-sm text-gray-500">
          <summary className="cursor-pointer hover:text-gray-700">
            {failed.length} failed/rejected actions
          </summary>
          <div className="mt-2 space-y-2">
            {failed.map((fix) => (
              <FixCard key={fix.id} fix={fix} />
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

function FixCard({
  fix,
  onApprove,
  onReject,
  onExecute,
  onApproveAndExecute,
  executing,
}: {
  fix: FixAction;
  onApprove?: () => void;
  onReject?: () => void;
  onExecute?: () => void;
  onApproveAndExecute?: () => void;
  executing?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="border border-gray-200 rounded-lg p-4 bg-white">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2 flex-1">
          <span>{actionTypeIcons[fix.action_type] || "📋"}</span>
          <span
            className={`text-xs px-2 py-0.5 rounded font-medium ${
              statusColors[fix.status] || "bg-gray-100 text-gray-800"
            }`}
          >
            {fix.status}
          </span>
          <span className="text-xs px-2 py-0.5 rounded bg-gray-100 text-gray-600">
            {fix.action_type.replace("_", " ")}
          </span>
          <h4 className="font-medium text-sm">{fix.title}</h4>
        </div>
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-xs text-gray-400 hover:text-gray-600 ml-2"
        >
          {expanded ? "▲" : "▼"}
        </button>
      </div>

      {fix.target_path && (
        <p className="text-xs text-gray-400 mt-1 font-mono">{fix.target_path}</p>
      )}

      {fix.description && (
        <p className="text-sm text-gray-600 mt-2">{fix.description}</p>
      )}

      {/* Expanded details */}
      {expanded && fix.fix_content && (
        <div className="mt-3 p-3 bg-gray-50 rounded text-xs font-mono overflow-auto max-h-60">
          <pre>{JSON.stringify(fix.fix_content, null, 2)}</pre>
        </div>
      )}

      {/* Execution result */}
      {fix.execution_result && (
        <div className="mt-3 p-3 bg-green-50 rounded text-xs">
          {fix.execution_result.pr_url && (
            <a
              href={String(fix.execution_result.pr_url)}
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-600 hover:underline"
            >
              🔗 View PR: {String(fix.execution_result.pr_url)}
            </a>
          )}
          {fix.execution_result.url && (
            <a
              href={String(fix.execution_result.url)}
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-600 hover:underline"
            >
              🔗 View updated post: {String(fix.execution_result.url)}
            </a>
          )}
          {fix.execution_result.error && (
            <p className="text-red-600">❌ {String(fix.execution_result.error)}</p>
          )}
          {fix.execution_result.steps && (
            <ul className="list-disc list-inside space-y-1 text-gray-700">
              {(fix.execution_result.steps as string[]).map((step, i) => (
                <li key={i}>{step}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Manual steps for recommendations */}
      {fix.status !== "completed" && fix.action_type === "recommendation" && fix.fix_content?.steps && (
        <div className="mt-3 p-3 bg-blue-50 rounded text-sm">
          <p className="font-medium text-blue-800 mb-1">📋 Manual Steps:</p>
          <ul className="list-decimal list-inside space-y-1 text-blue-900">
            {(Array.isArray(fix.fix_content.steps)
              ? fix.fix_content.steps
              : (fix.fix_content.steps as string).split(/\d+\.\s*/).filter(Boolean)
            ).map((step: string, i: number) => (
              <li key={i}>{step}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Action buttons */}
      {(onApprove || onReject || onExecute || onApproveAndExecute) && (
        <div className="flex gap-2 mt-3 pt-3 border-t border-gray-100">
          {onApproveAndExecute && (
            <button
              onClick={onApproveAndExecute}
              disabled={executing}
              className="px-3 py-1.5 text-xs font-medium rounded bg-green-600 text-white hover:bg-green-700 disabled:opacity-50"
            >
              {executing ? "Executing..." : "✓ Approve & Execute"}
            </button>
          )}
          {onApprove && (
            <button
              onClick={onApprove}
              className="px-3 py-1.5 text-xs font-medium rounded bg-blue-600 text-white hover:bg-blue-700"
            >
              ✓ Approve
            </button>
          )}
          {onExecute && (
            <button
              onClick={onExecute}
              disabled={executing}
              className="px-3 py-1.5 text-xs font-medium rounded bg-green-600 text-white hover:bg-green-700 disabled:opacity-50"
            >
              {executing ? "Executing..." : "▶ Execute"}
            </button>
          )}
          {onReject && (
            <button
              onClick={onReject}
              className="px-3 py-1.5 text-xs font-medium rounded border border-gray-300 text-gray-600 hover:bg-gray-50"
            >
              ✗ Reject
            </button>
          )}
        </div>
      )}
    </div>
  );
}
