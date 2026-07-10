"use client";

import { useState } from "react";
import useSWR from "swr";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type JsonRecord = Record<string, unknown>;

interface FixAction {
  id: string;
  site_id: string;
  issue_id: string;
  action_type: string;
  status: string;
  title: string;
  description: string | null;
  fix_content: JsonRecord | null;
  target_path: string | null;
  execution_result: JsonRecord | null;
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

async function fetcher(url: string): Promise<FixAction[]> {
  const response = await fetch(url);
  if (!response.ok) throw new Error("Failed to fetch fix actions");
  return response.json() as Promise<FixAction[]>;
}

function hasValue(value: unknown): boolean {
  return value !== null && value !== undefined && value !== "";
}

function asText(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean" || typeof value === "bigint") {
    return String(value);
  }
  if (value === null || value === undefined) return "";

  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map(asText).filter(Boolean) : [];
}

export default function FixActionsPanel({ siteId }: { siteId: string }) {
  const { data: fixes, error, mutate } = useSWR<FixAction[]>(
    `${API_URL}/actions/fixes/${siteId}`,
    fetcher,
  );
  const [generating, setGenerating] = useState(false);
  const [executing, setExecuting] = useState<string | null>(null);

  if (error) return null;
  if (!fixes) {
    return (
      <div className="animate-pulse space-y-3">
        {[1, 2, 3].map((item) => (
          <div key={item} className="h-20 rounded bg-gray-200" />
        ))}
      </div>
    );
  }

  async function post(url: string, body?: JsonRecord) {
    const response = await fetch(url, {
      method: "POST",
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });

    if (!response.ok) throw new Error(`Request failed with status ${response.status}`);
    await mutate();
  }

  async function generateFixPlans() {
    setGenerating(true);
    try {
      await post(`${API_URL}/actions/fix-plan-bulk/${siteId}?max_issues=10`, {});
    } finally {
      setGenerating(false);
    }
  }

  async function approveAction(fixId: string) {
    await post(`${API_URL}/actions/fix/${fixId}/approve`, { action: "approve" });
  }

  async function rejectAction(fixId: string) {
    await post(`${API_URL}/actions/fix/${fixId}/approve`, { action: "reject" });
  }

  async function executeAction(fixId: string) {
    setExecuting(fixId);
    try {
      await post(`${API_URL}/actions/fix/${fixId}/execute`);
    } finally {
      setExecuting(null);
    }
  }

  async function approveAndExecute(fixId: string) {
    setExecuting(fixId);
    try {
      await post(`${API_URL}/actions/approve-and-execute/${fixId}`);
    } finally {
      setExecuting(null);
    }
  }

  const pending = fixes.filter((fix) => fix.status === "pending");
  const approved = fixes.filter((fix) => fix.status === "approved");
  const completed = fixes.filter((fix) => fix.status === "completed");
  const failed = fixes.filter((fix) => ["failed", "rejected"].includes(fix.status));

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <h3 className="text-lg font-semibold">Fix Actions ({fixes.length})</h3>
        <button
          type="button"
          onClick={generateFixPlans}
          disabled={generating}
          className={`rounded-md px-4 py-2 text-sm font-medium ${
            generating
              ? "cursor-not-allowed bg-gray-100 text-gray-400"
              : "bg-blue-600 text-white hover:bg-blue-700"
          }`}
        >
          {generating ? "Generating..." : "Generate Fix Plans"}
        </button>
      </div>

      {fixes.length > 0 && (
        <div className="flex flex-wrap gap-2 text-xs">
          <StatusCount className="bg-yellow-100 text-yellow-800" label="pending" count={pending.length} />
          <StatusCount className="bg-blue-100 text-blue-800" label="approved" count={approved.length} />
          <StatusCount className="bg-green-100 text-green-800" label="completed" count={completed.length} />
          {failed.length > 0 && (
            <StatusCount className="bg-red-100 text-red-800" label="failed/rejected" count={failed.length} />
          )}
        </div>
      )}

      {fixes.length === 0 && (
        <div className="py-12 text-center text-gray-500">
          <p className="text-lg font-medium">No fix plans yet</p>
          <p className="mt-1 text-sm">
            Click &quot;Generate Fix Plans&quot; to create reviewed fixes for your SEO issues.
          </p>
        </div>
      )}

      <ActionGroup title="⏳ Pending Approval">
        {pending.map((fix) => (
          <FixCard
            key={fix.id}
            fix={fix}
            executing={executing === fix.id}
            onApprove={() => approveAction(fix.id)}
            onReject={() => rejectAction(fix.id)}
            onApproveAndExecute={() => approveAndExecute(fix.id)}
          />
        ))}
      </ActionGroup>

      <ActionGroup title="✅ Approved — Ready to Execute">
        {approved.map((fix) => (
          <FixCard
            key={fix.id}
            fix={fix}
            executing={executing === fix.id}
            onExecute={() => executeAction(fix.id)}
          />
        ))}
      </ActionGroup>

      <ActionGroup title="🎉 Completed">
        {completed.map((fix) => (
          <FixCard key={fix.id} fix={fix} />
        ))}
      </ActionGroup>

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

function StatusCount({ className, label, count }: { className: string; label: string; count: number }) {
  return <span className={`rounded px-2 py-1 ${className}`}>{count} {label}</span>;
}

function ActionGroup({ title, children }: { title: string; children: React.ReactNode }) {
  if (!children || (Array.isArray(children) && children.length === 0)) return null;

  return (
    <div className="space-y-3">
      <h4 className="text-sm font-medium text-gray-700">{title}</h4>
      {children}
    </div>
  );
}

function FixCard({
  fix,
  onApprove,
  onReject,
  onExecute,
  onApproveAndExecute,
  executing = false,
}: {
  fix: FixAction;
  onApprove?: () => void;
  onReject?: () => void;
  onExecute?: () => void;
  onApproveAndExecute?: () => void;
  executing?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const content = fix.fix_content ?? {};
  const result = fix.execution_result;
  const filesChanged = asStringArray(result?.files_changed);
  const hasStructuredContent = [
    content.affected_url,
    content.current_value,
    content.recommended_value,
    content.instructions,
    content.file_path,
  ].some(hasValue);

  return (
    <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
      <button
        type="button"
        className="block w-full p-4 text-left transition-colors hover:bg-gray-50"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 flex-1 items-center gap-2">
            <span className="shrink-0 text-lg">{actionTypeIcons[fix.action_type] || "📋"}</span>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className={`rounded px-2 py-0.5 text-xs font-medium ${statusColors[fix.status] || "bg-gray-100 text-gray-800"}`}>
                  {fix.status}
                </span>
                <h4 className="text-sm font-medium text-gray-900">{fix.title}</h4>
              </div>
              {fix.target_path && <p className="mt-0.5 truncate font-mono text-xs text-gray-400">{fix.target_path}</p>}
            </div>
          </div>
          <span className="shrink-0 text-xs text-gray-400">{expanded ? "▲" : "▼"}</span>
        </div>
        {fix.description && <p className="mt-2 line-clamp-2 text-sm text-gray-600">{fix.description}</p>}
      </button>

      {expanded && (
        <div className="border-t border-gray-100">
          {hasStructuredContent && (
            <div className="space-y-3 bg-gray-50 px-4 py-3">
              <Detail label="Affected URL" value={content.affected_url} monospace />
              <Detail label="Current (Problem)" value={content.current_value} tone="danger" />
              <Detail label="Recommended Fix" value={content.recommended_value} tone="success" />
              <Detail label="Instructions" value={content.instructions} tone="neutral" preserveWhitespace />
              <Detail label="Target File" value={content.file_path} monospace />
            </div>
          )}

          {!hasStructuredContent && fix.fix_content && (
            <div className="bg-gray-50 px-4 py-3">
              <details className="text-xs">
                <summary className="cursor-pointer text-gray-500 hover:text-gray-700">View raw fix data</summary>
                <pre className="mt-2 max-h-40 overflow-auto font-mono text-xs text-gray-600">
                  {JSON.stringify(fix.fix_content, null, 2)}
                </pre>
              </details>
            </div>
          )}

          {result && (
            <div className="space-y-2 border-t border-gray-100 px-4 py-3">
              {hasValue(result.pr_url) && (
                <ExternalLink href={asText(result.pr_url)} label="🔀 View Pull Request" />
              )}
              {filesChanged.length > 0 && (
                <div>
                  <span className="text-xs text-gray-500">Files changed:</span>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {filesChanged.map((file) => (
                      <span key={file} className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-xs">{file}</span>
                    ))}
                  </div>
                </div>
              )}
              {hasValue(result.url) && <ExternalLink href={asText(result.url)} label="🔗 View updated page" />}
              {result.status === "no_changes" && (
                <p className="rounded bg-amber-50 px-3 py-2 text-sm text-amber-700">No file changes were produced. Manual review is required.</p>
              )}
              {result.status === "recommendation" && (
                <p className="rounded bg-blue-50 px-3 py-2 text-sm text-blue-700">This action is a manual recommendation. Follow the instructions above.</p>
              )}
              {hasValue(result.error) && (
                <p className="rounded bg-red-50 px-3 py-2 text-sm text-red-700">{asText(result.error)}</p>
              )}
            </div>
          )}

          {(onApprove || onReject || onExecute || onApproveAndExecute) && (
            <div className="flex flex-wrap items-center gap-2 border-t border-gray-100 bg-white px-4 py-3">
              {onApproveAndExecute && (
                <button
                  type="button"
                  onClick={onApproveAndExecute}
                  disabled={executing}
                  className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
                >
                  {executing ? "Executing..." : "Approve & Execute"}
                </button>
              )}
              {onApprove && (
                <button type="button" onClick={onApprove} className="rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700">
                  Approve
                </button>
              )}
              {onExecute && (
                <button type="button" onClick={onExecute} disabled={executing} className="rounded-md bg-green-600 px-3 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50">
                  {executing ? "Executing..." : "Execute"}
                </button>
              )}
              {onReject && (
                <button type="button" onClick={onReject} className="rounded-md border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">
                  Reject
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Detail({
  label,
  value,
  tone,
  monospace = false,
  preserveWhitespace = false,
}: {
  label: string;
  value: unknown;
  tone?: "danger" | "success" | "neutral";
  monospace?: boolean;
  preserveWhitespace?: boolean;
}) {
  if (!hasValue(value)) return null;

  const toneClass = tone === "danger"
    ? "bg-red-50 text-red-700"
    : tone === "success"
      ? "bg-green-50 text-green-700"
      : tone === "neutral"
        ? "border border-gray-200 bg-white text-gray-700"
        : "text-gray-800";

  return (
    <div>
      <span className="text-xs font-medium uppercase text-gray-500">{label}</span>
      <div className={`mt-0.5 rounded px-2 py-1 text-sm ${toneClass} ${monospace ? "font-mono" : ""} ${preserveWhitespace ? "whitespace-pre-wrap" : ""}`}>
        {asText(value)}
      </div>
    </div>
  );
}

function ExternalLink({ href, label }: { href: string; label: string }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 text-sm font-medium text-blue-600 hover:underline">
      {label}
    </a>
  );
}
