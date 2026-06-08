"use client";

import { useState } from "react";
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

interface SiteInfo {
  domain?: string;
  github_repo?: string;
  tech_stack?: string;
}

const severityColors: Record<string, string> = {
  critical: "bg-red-100 text-red-800",
  high: "bg-orange-100 text-orange-800",
  medium: "bg-yellow-100 text-yellow-800",
  low: "bg-blue-100 text-blue-800",
};

const categoryIcons: Record<string, string> = {
  seo: "🔍",
  technical: "🔧",
  content: "📝",
  accessibility: "♿",
  structure: "🏗️",
  performance: "⚡",
  opportunity: "💡",
};

type SeverityFilter = "all" | "high" | "medium" | "low";
type CategoryFilter = "all" | string;

export default function IssuesPanel({ siteId, site }: { siteId: string; site?: SiteInfo }) {
  const [severityFilter, setSeverityFilter] = useState<SeverityFilter>("all");
  const [categoryFilter, setCategoryFilter] = useState<CategoryFilter>("all");
  const [copied, setCopied] = useState(false);
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

  function generatePrompt(issuesToInclude: Issue[]): string {
    const codeFixable = issuesToInclude.filter(
      (i) => i.category !== "opportunity" && i.status === "open"
    );
    if (codeFixable.length === 0) return "";

    const domain = site?.domain || "the website";
    const repo = site?.github_repo || "";
    const techStack = site?.tech_stack || "";

    let prompt = `Fix the following SEO issues on ${domain}.\n`;
    if (repo) prompt += `Repository: ${repo}\n`;
    if (techStack) prompt += `Tech stack: ${techStack}\n`;
    prompt += `\nThere are ${codeFixable.length} issues to fix. For each one, make the necessary code changes.\n`;
    prompt += `Make sure the build passes after your changes.\n\n`;
    prompt += `---\n\n`;

    codeFixable.forEach((issue, idx) => {
      prompt += `## Issue ${idx + 1}: ${issue.title}\n`;
      prompt += `- Severity: ${issue.severity}\n`;
      prompt += `- Category: ${issue.category}\n`;
      if (issue.affected_url) prompt += `- Affected URL: ${issue.affected_url}\n`;
      prompt += `- Problem: ${issue.description}\n`;
      if (issue.recommendation) prompt += `- Fix: ${issue.recommendation}\n`;
      prompt += `\n`;
    });

    return prompt;
  }

  async function copyPrompt() {
    const prompt = generatePrompt(filteredIssues);
    if (!prompt) return;
    await navigator.clipboard.writeText(prompt);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  const openIssues = issues.filter((i) => i.status === "open");
  const dismissedIssues = issues.filter((i) => i.status !== "open");

  // Severity counts
  const highCount = openIssues.filter((i) => i.severity === "high" || i.severity === "critical").length;
  const mediumCount = openIssues.filter((i) => i.severity === "medium").length;
  const lowCount = openIssues.filter((i) => i.severity === "low").length;

  // Category counts
  const categories = [...new Set(openIssues.map((i) => i.category))].sort();

  // Apply filters
  let filteredIssues = openIssues;
  if (severityFilter === "high") {
    filteredIssues = filteredIssues.filter((i) => i.severity === "high" || i.severity === "critical");
  } else if (severityFilter !== "all") {
    filteredIssues = filteredIssues.filter((i) => i.severity === severityFilter);
  }
  if (categoryFilter !== "all") {
    filteredIssues = filteredIssues.filter((i) => i.category === categoryFilter);
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold">
          Issues ({openIssues.length} open)
        </h3>
        <div className="flex items-center gap-3">
          <button
            onClick={copyPrompt}
            className={`px-3 py-1.5 text-xs font-medium rounded-md border transition-colors ${
              copied
                ? "bg-green-100 text-green-800 border-green-300"
                : "bg-white text-gray-700 border-gray-300 hover:bg-gray-50 hover:border-gray-400"
            }`}
          >
            {copied ? "✓ Copied!" : "📋 Copy Prompt for Coding Agent"}
          </button>
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
      </div>

      {/* Severity filter buttons */}
      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => setSeverityFilter("all")}
          className={`px-3 py-1.5 text-xs font-medium rounded-full border ${
            severityFilter === "all"
              ? "bg-gray-900 text-white border-gray-900"
              : "bg-white text-gray-600 border-gray-300 hover:border-gray-400"
          }`}
        >
          All Issues ({openIssues.length})
        </button>
        <button
          onClick={() => setSeverityFilter("high")}
          className={`px-3 py-1.5 text-xs font-medium rounded-full border ${
            severityFilter === "high"
              ? "bg-red-600 text-white border-red-600"
              : "bg-white text-red-700 border-red-300 hover:border-red-400"
          }`}
        >
          🔴 Errors ({highCount})
        </button>
        <button
          onClick={() => setSeverityFilter("medium")}
          className={`px-3 py-1.5 text-xs font-medium rounded-full border ${
            severityFilter === "medium"
              ? "bg-yellow-500 text-white border-yellow-500"
              : "bg-white text-yellow-700 border-yellow-300 hover:border-yellow-400"
          }`}
        >
          🟡 Warnings ({mediumCount})
        </button>
        <button
          onClick={() => setSeverityFilter("low")}
          className={`px-3 py-1.5 text-xs font-medium rounded-full border ${
            severityFilter === "low"
              ? "bg-blue-600 text-white border-blue-600"
              : "bg-white text-blue-700 border-blue-300 hover:border-blue-400"
          }`}
        >
          🔵 Info ({lowCount})
        </button>

        <span className="border-l border-gray-300 mx-1" />

        {/* Category filter */}
        <button
          onClick={() => setCategoryFilter("all")}
          className={`px-3 py-1.5 text-xs font-medium rounded-full border ${
            categoryFilter === "all"
              ? "bg-gray-900 text-white border-gray-900"
              : "bg-white text-gray-600 border-gray-300 hover:border-gray-400"
          }`}
        >
          All Categories
        </button>
        {categories.map((cat) => (
          <button
            key={cat}
            onClick={() => setCategoryFilter(cat)}
            className={`px-3 py-1.5 text-xs font-medium rounded-full border ${
              categoryFilter === cat
                ? "bg-gray-700 text-white border-gray-700"
                : "bg-white text-gray-600 border-gray-300 hover:border-gray-400"
            }`}
          >
            {categoryIcons[cat] || "📋"} {cat}
          </button>
        ))}
      </div>

      {/* Filtered count */}
      {(severityFilter !== "all" || categoryFilter !== "all") && (
        <p className="text-sm text-gray-500">
          Showing {filteredIssues.length} of {openIssues.length} issues
        </p>
      )}

      {filteredIssues.map((issue) => (
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
