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
  const content = fix.fix_content || {};

  return (
    <div className="border border-gray-200 rounded-lg bg-white overflow-hidden">
      {/* Header */}
      <div
        className="p-4 cursor-pointer hover:bg-gray-50 transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2 flex-1 min-w-0">
            <span className="text-lg shrink-0">{actionTypeIcons[fix.action_type] || "📋"}</span>
            <div className="min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span
                  className={`text-xs px-2 py-0.5 rounded font-medium ${
                    statusColors[fix.status] || "bg-gray-100 text-gray-800"
                  }`}
                >
                  {fix.status}
                </span>
                <h4 className="font-medium text-sm text-gray-900">{fix.title}</h4>
              </div>
              {fix.target_path && (
                <p className="text-xs text-gray-400 mt-0.5 font-mono truncate">
                  {fix.target_path}
                </p>
              )}
            </div>
          </div>
          <span className="text-gray-400 text-xs ml-2 shrink-0">
            {expanded ? "▲" : "▼"}
          </span>
        </div>

        {fix.description && (
          <p className="text-sm text-gray-600 mt-2 line-clamp-2">{fix.description}</p>
        )}
      </div>

      {/* Expanded details */}
      {expanded && (
        <div className="border-t border-gray-100">
          {/* Fix content - human-readable */}
          {(content.affected_url || content.current_value || content.recommended_value || content.instructions) && (
            <div className="px-4 py-3 space-y-3 bg-gray-50">
              {content.affected_url && (
                <div>
                  <span className="text-xs font-medium text-gray-500 uppercase">Affected URL</span>
                  <p className="text-sm font-mono text-gray-800 mt-0.5">{String(content.affected_url)}</p>
                </div>
              )}
              {content.current_value && (
                <div>
                  <span className="text-xs font-medium text-gray-500 uppercase">Current (Problem)</span>
                  <p className="text-sm text-red-700 bg-red-50 px-2 py-1 rounded mt-0.5">{String(content.current_value)}</p>
                </div>
              )}
              {content.recommended_value && (
                <div>
                  <span className="text-xs font-medium text-gray-500 uppercase">Recommended Fix</span>
                  <p className="text-sm text-green-700 bg-green-50 px-2 py-1 rounded mt-0.5">{String(content.recommended_value)}</p>
                </div>
              )}
              {content.instructions && (
                <div>
                  <span className="text-xs font-medium text-gray-500 uppercase">Instructions</span>
                  <div className="text-sm text-gray-700 mt-1 whitespace-pre-wrap bg-white border border-gray-200 rounded p-3">
                    {String(content.instructions)}
                  </div>
                </div>
              )}
              {content.file_path && (
                <div>
                  <span className="text-xs font-medium text-gray-500 uppercase">Target File</span>
                  <p className="text-sm font-mono text-gray-600 mt-0.5">{String(content.file_path)}</p>
                </div>
              )}
            </div>
          )}

          {/* Legacy: raw JSON for old fix plans without structured content */}
          {!content.instructions && !content.current_value && !content.recommended_value && fix.fix_content && (
            <div className="px-4 py-3 bg-gray-50">
              <details className="text-xs">
                <summary className="cursor-pointer text-gray-500 hover:text-gray-700">View raw fix data</summary>
                <pre className="mt-2 overflow-auto max-h-40 text-xs font-mono text-gray-600">
                  {JSON.stringify(fix.fix_content, null, 2)}
                </pre>
              </details>
            </div>
          )}

          {/* Execution result */}
          {fix.execution_result && (
            <div className="px-4 py-3 border-t border-gray-100">
              {fix.execution_result.pr_url && (
                <a
                  href={String(fix.execution_result.pr_url)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 text-sm text-blue-600 hover:underline font-medium"
                >
                  🔀 View Pull Request
                </a>
              )}
              {fix.execution_result.files_changed && (
                <div className="mt-2">
                  <span className="text-xs text-gray-500">Files changed:</span>
                  <div className="flex flex-wrap gap-1 mt-1">
                    {(fix.execution_result.files_changed as string[]).map((f, i) => (
                      <span key={i} className="text-xs font-mono bg-gray-100 px-1.5 py-0.5 rounded">{f}</span>
                    ))}
                  </div>
                </div>
              )}
              {fix.execution_result.url && (
                <a
                  href={String(fix.execution_result.url)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 text-sm text-blue-600 hover:underline"
                >
                  🔗 View updated page
                </a>
              )}
              {fix.execution_result.status === "no_changes" && (
                <p className="text-sm text-amber-700 bg-amber-50 px-3 py-2 rounded">
                  ⚠️ Codex ran but made no file changes. The issue may require manual intervention.
                </p>
              )}
              {fix.execution_result.status === "recommendation" && (
                <p className="text-sm text-blue-700 bg-blue-50 px-3 py-2 rounded">
                  ℹ️ This is a manual recommendation — follow the instructions above to fix.
                </p>
              )}
              {fix.execution_result.error && (
                <p className="text-sm text-red-700 bg-red-50 px-3 py-2 rounded">
                  ❌ {String(fix.execution_result.error)}
                </p>
              )}
            </div>
          )}

          {/* Action buttons */}
          {(onApprove || onReject || onExecute || onApproveAndExecute) && (
            <div className="flex items-center gap-2 px-4 py-3 border-t border-gray-100 bg-white">
              {onApproveAndExecute && fix.action_type === "github_pr" && (
                <button
                  onClick={onApproveAndExecute}
                  disabled={executing}
                  className="px-4 py-2 text-sm font-medium rounded-md bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50 flex items-center gap-1.5"
                >
                  {executing ? (
                    <>
                      <span className="h-3.5 w-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                      Running Codex...
                    </>
                  ) : (
                    "🤖 Run with Codex"
                  )}
                </button>
              )}
              {onApproveAndExecute && fix.action_type !== "github_pr" && (
                <button
                  onClick={onApproveAndExecute}
                  disabled={executing}
                  className="px-4 py-2 text-sm font-medium rounded-md bg-green-600 text-white hover:bg-green-700 disabled:opacity-50"
                >
                  {executing ? "Executing..." : "✓ Approve & Execute"}
                </button>
              )}
              {onApprove && (
                <button
                  onClick={onApprove}
                  className="px-3 py-2 text-sm font-medium rounded-md bg-blue-600 text-white hover:bg-blue-700"
                >
                  ✓ Approve
                </button>
              )}
              {onExecute && (
                <button
                  onClick={onExecute}
                  disabled={executing}
                  className="px-3 py-2 text-sm font-medium rounded-md bg-green-600 text-white hover:bg-green-700 disabled:opacity-50"
                >
                  {executing ? "Running..." : "▶ Execute"}
                </button>
              )}
              {onReject && (
                <button
                  onClick={onReject}
                  className="px-3 py-2 text-sm font-medium rounded-md border border-gray-300 text-gray-600 hover:bg-gray-50"
                >
                  ✗ Dismiss
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
