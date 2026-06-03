"use client";

import { use, useState } from "react";
import useSWR from "swr";
import SiteHeader from "@/components/sites/site-header";
import StatCards from "@/components/sites/stat-cards";
import PagesTable from "@/components/sites/pages-table";
import IssuesPanel from "@/components/sites/issues-panel";
import FixActionsPanel from "@/components/sites/fix-actions-panel";
import IntegrationsPanel from "@/components/sites/integrations-panel";
import AgentChatPanel from "@/components/sites/agent-chat-panel";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function fetcher(url: string) {
  const res = await fetch(url);
  if (!res.ok) throw new Error("Failed to fetch");
  return res.json();
}

export default function SiteDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const { data: site, error, mutate } = useSWR(`${API_URL}/sites/${id}`, fetcher);
  const [activeTab, setActiveTab] = useState<"agent" | "pages" | "issues" | "fixes" | "integrations">("agent");
  const [issueKey, setIssueKey] = useState(0);

  if (error) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <p className="text-red-600">Site not found</p>
      </div>
    );
  }

  if (!site) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="h-8 w-8 border-4 border-blue-600 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  function handleAgentComplete() {
    setIssueKey((k) => k + 1);
    setActiveTab("issues");
    mutate();
  }

  const tabs = [
    { key: "agent", label: "💬 Agent" },
    { key: "pages", label: "Pages" },
    { key: "issues", label: "Issues" },
    { key: "fixes", label: "Fix Actions" },
    { key: "integrations", label: "Integrations" },
  ] as const;

  return (
    <div className="min-h-screen bg-gray-50">
      <SiteHeader site={site} onAgentComplete={handleAgentComplete} />
      <main className="max-w-7xl mx-auto px-6 py-8">
        <StatCards site={site} />
        <div className="mt-8">
          <div className="border-b border-gray-200 mb-6">
            <nav className="flex gap-6">
              {tabs.map((tab) => (
                <button
                  key={tab.key}
                  onClick={() => setActiveTab(tab.key)}
                  className={`pb-3 text-sm font-medium border-b-2 ${
                    activeTab === tab.key
                      ? "border-blue-600 text-blue-600"
                      : "border-transparent text-gray-500 hover:text-gray-700"
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </nav>
          </div>
          {activeTab === "agent" && <AgentChatPanel siteId={id} />}
          {activeTab === "pages" && <PagesTable siteId={id} />}
          {activeTab === "issues" && <IssuesPanel key={issueKey} siteId={id} />}
          {activeTab === "fixes" && <FixActionsPanel siteId={id} />}
          {activeTab === "integrations" && <IntegrationsPanel siteId={id} />}
        </div>
      </main>
    </div>
  );
}
