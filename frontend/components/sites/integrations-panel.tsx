"use client";

import { useState } from "react";
import useSWR from "swr";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function fetcher(url: string) {
  const res = await fetch(url);
  if (!res.ok) throw new Error("Failed to fetch");
  return res.json();
}

interface IntegrationStatus {
  github_repo: string | null;
  github_connected: boolean;
  wordpress_url: string | null;
  wordpress_connected: boolean;
  tech_stack: string | null;
  cms: string | null;
}

export default function IntegrationsPanel({ siteId }: { siteId: string }) {
  const { data: integrations, error, mutate } = useSWR<IntegrationStatus>(
    `${API_URL}/actions/integrations/${siteId}`,
    fetcher
  );
  const [detecting, setDetecting] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [verifyResult, setVerifyResult] = useState<Record<string, unknown> | null>(null);
  const [saving, setSaving] = useState(false);
  const [showForm, setShowForm] = useState(false);

  // Form state
  const [githubRepo, setGithubRepo] = useState("");
  const [githubToken, setGithubToken] = useState("");
  const [wpUrl, setWpUrl] = useState("");
  const [wpUser, setWpUser] = useState("");
  const [wpPassword, setWpPassword] = useState("");

  if (error) return null;
  if (!integrations) {
    return (
      <div className="animate-pulse space-y-3">
        <div className="h-32 bg-gray-200 rounded" />
        <div className="h-32 bg-gray-200 rounded" />
      </div>
    );
  }

  async function detectTech() {
    setDetecting(true);
    try {
      await fetch(`${API_URL}/actions/detect-tech/${siteId}`, { method: "POST" });
      mutate();
    } finally {
      setDetecting(false);
    }
  }

  async function saveIntegrations() {
    setSaving(true);
    try {
      const body: Record<string, string> = {};
      if (githubRepo) body.github_repo = githubRepo;
      if (githubToken) body.github_token = githubToken;
      if (wpUrl) body.wordpress_url = wpUrl;
      if (wpUser) body.wordpress_user = wpUser;
      if (wpPassword) body.wordpress_app_password = wpPassword;

      await fetch(`${API_URL}/actions/integrations/${siteId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      mutate();
      setShowForm(false);
      setGithubToken("");
      setWpPassword("");
    } finally {
      setSaving(false);
    }
  }

  async function verifyConnections() {
    setVerifying(true);
    try {
      const res = await fetch(`${API_URL}/actions/integrations/${siteId}/verify`, {
        method: "POST",
      });
      const data = await res.json();
      setVerifyResult(data);
    } finally {
      setVerifying(false);
    }
  }

  return (
    <div className="space-y-6">
      <h3 className="text-lg font-semibold">Integrations & Settings</h3>

      {/* Tech Stack Detection */}
      <div className="border border-gray-200 rounded-lg p-4 bg-white">
        <div className="flex items-center justify-between">
          <div>
            <h4 className="font-medium text-sm">🔍 Technology Detection</h4>
            <p className="text-xs text-gray-500 mt-1">
              Auto-detect the framework and CMS used by your site
            </p>
          </div>
          <button
            onClick={detectTech}
            disabled={detecting}
            className="px-3 py-1.5 text-xs font-medium rounded bg-gray-100 text-gray-700 hover:bg-gray-200 disabled:opacity-50"
          >
            {detecting ? "Detecting..." : "Re-detect"}
          </button>
        </div>
        <div className="flex gap-3 mt-3">
          <div className="px-3 py-2 bg-gray-50 rounded flex-1">
            <p className="text-xs text-gray-500">Framework</p>
            <p className="text-sm font-medium">
              {integrations.tech_stack || "Not detected"}
            </p>
          </div>
          <div className="px-3 py-2 bg-gray-50 rounded flex-1">
            <p className="text-xs text-gray-500">CMS</p>
            <p className="text-sm font-medium">
              {integrations.cms === "none" ? "None" : integrations.cms || "Not detected"}
            </p>
          </div>
        </div>
      </div>

      {/* GitHub Integration */}
      <div className="border border-gray-200 rounded-lg p-4 bg-white">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-lg">🔀</span>
            <div>
              <h4 className="font-medium text-sm">GitHub Integration</h4>
              <p className="text-xs text-gray-500">
                Auto-create PRs with SEO code fixes
              </p>
            </div>
          </div>
          <span
            className={`text-xs px-2 py-1 rounded font-medium ${
              integrations.github_connected
                ? "bg-green-100 text-green-800"
                : "bg-gray-100 text-gray-500"
            }`}
          >
            {integrations.github_connected ? "Connected" : "Not connected"}
          </span>
        </div>
        {integrations.github_repo && (
          <p className="text-xs text-gray-600 mt-2 font-mono bg-gray-50 px-2 py-1 rounded">
            📂 {integrations.github_repo}
          </p>
        )}
      </div>

      {/* WordPress Integration */}
      <div className="border border-gray-200 rounded-lg p-4 bg-white">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-lg">📝</span>
            <div>
              <h4 className="font-medium text-sm">WordPress Integration</h4>
              <p className="text-xs text-gray-500">
                Auto-update posts/pages via REST API
              </p>
            </div>
          </div>
          <span
            className={`text-xs px-2 py-1 rounded font-medium ${
              integrations.wordpress_connected
                ? "bg-green-100 text-green-800"
                : "bg-gray-100 text-gray-500"
            }`}
          >
            {integrations.wordpress_connected ? "Connected" : "Not connected"}
          </span>
        </div>
        {integrations.wordpress_url && (
          <p className="text-xs text-gray-600 mt-2 font-mono bg-gray-50 px-2 py-1 rounded">
            🌐 {integrations.wordpress_url}
          </p>
        )}
      </div>

      {/* Configure / Edit */}
      {!showForm ? (
        <div className="flex gap-2">
          <button
            onClick={() => setShowForm(true)}
            className="px-4 py-2 text-sm font-medium rounded bg-blue-600 text-white hover:bg-blue-700"
          >
            Configure Integrations
          </button>
          {(integrations.github_connected || integrations.wordpress_connected) && (
            <button
              onClick={verifyConnections}
              disabled={verifying}
              className="px-4 py-2 text-sm font-medium rounded border border-gray-300 text-gray-700 hover:bg-gray-50 disabled:opacity-50"
            >
              {verifying ? "Verifying..." : "Test Connections"}
            </button>
          )}
        </div>
      ) : (
        <div className="border border-blue-200 rounded-lg p-4 bg-blue-50 space-y-4">
          <h4 className="font-medium text-sm text-blue-900">Configure Integrations</h4>

          {/* GitHub Fields */}
          <div className="space-y-2">
            <p className="text-xs font-medium text-gray-700">GitHub</p>
            <input
              type="text"
              placeholder="owner/repo (e.g., myuser/mysite)"
              value={githubRepo}
              onChange={(e) => setGithubRepo(e.target.value)}
              className="w-full px-3 py-2 text-sm border border-gray-300 rounded focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            />
            <input
              type="password"
              placeholder="GitHub Personal Access Token"
              value={githubToken}
              onChange={(e) => setGithubToken(e.target.value)}
              className="w-full px-3 py-2 text-sm border border-gray-300 rounded focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            />
          </div>

          {/* WordPress Fields */}
          <div className="space-y-2">
            <p className="text-xs font-medium text-gray-700">WordPress</p>
            <input
              type="text"
              placeholder="Site URL (e.g., https://myblog.com)"
              value={wpUrl}
              onChange={(e) => setWpUrl(e.target.value)}
              className="w-full px-3 py-2 text-sm border border-gray-300 rounded focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            />
            <input
              type="text"
              placeholder="WordPress Username"
              value={wpUser}
              onChange={(e) => setWpUser(e.target.value)}
              className="w-full px-3 py-2 text-sm border border-gray-300 rounded focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            />
            <input
              type="password"
              placeholder="Application Password"
              value={wpPassword}
              onChange={(e) => setWpPassword(e.target.value)}
              className="w-full px-3 py-2 text-sm border border-gray-300 rounded focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            />
          </div>

          <div className="flex gap-2">
            <button
              onClick={saveIntegrations}
              disabled={saving}
              className="px-4 py-2 text-sm font-medium rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {saving ? "Saving..." : "Save"}
            </button>
            <button
              onClick={() => setShowForm(false)}
              className="px-4 py-2 text-sm font-medium rounded border border-gray-300 text-gray-600 hover:bg-gray-50"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Verify Results */}
      {verifyResult && (
        <div className="border border-gray-200 rounded-lg p-4 bg-white space-y-2">
          <h4 className="font-medium text-sm">Connection Test Results</h4>
          {Object.entries(verifyResult).map(([key, value]) => (
            <div key={key} className="flex items-center gap-2 text-sm">
              <span>
                {(value as { connected?: boolean })?.connected ? "✅" : "❌"}
              </span>
              <span className="font-medium capitalize">{key}:</span>
              <span className="text-gray-600">
                {(value as { connected?: boolean })?.connected
                  ? "Connected"
                  : (value as { error?: string; reason?: string })?.error ||
                    (value as { reason?: string })?.reason ||
                    "Failed"}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
