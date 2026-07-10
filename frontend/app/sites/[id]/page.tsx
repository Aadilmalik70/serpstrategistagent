"use client";

import { use, useState } from "react";
import { useSession } from "next-auth/react";
import useSWR from "swr";

import AgentChatPanel from "@/components/sites/agent-chat-panel";
import EEATPanel from "@/components/sites/eeat-panel";
import FixActionsPanel from "@/components/sites/fix-actions-panel";
import IntegrationsPanel from "@/components/sites/integrations-panel";
import IssuesPanel from "@/components/sites/issues-panel";
import LinksPanel from "@/components/sites/links-panel";
import PagesTable from "@/components/sites/pages-table";
import SiteHeader from "@/components/sites/site-header";
import StatCards from "@/components/sites/stat-cards";
import StatusCodesPanel from "@/components/sites/status-codes-panel";
import VisualizationPanel from "@/components/sites/visualization-panel";
import { apiFetch } from "@/lib/api";

type SiteDetail = {
  id: string;
  name: string;
  domain: string;
  status: string;
  updated_at: string;
  page_count: number;
  issue_count: number;
  tech_stack?: string | null;
  github_repo?: string;
  health_score: number | null;
  health_grade: string | null;
  latest_run: {
    issues_found: number;
    pages_analyzed: number;
    summary: string | null;
    completed_at: string | null;
  } | null;
  librecrawl_enabled: boolean;
};

export default function SiteDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const { data: session } = useSession();
  const canUseApi = Boolean(session?.accessToken && session.workspaceId);
  const { data: site, error, mutate } = useSWR<SiteDetail>(
    canUseApi ? `/sites/${id}` : null,
    apiFetch,
  );
  const [activeTab, setActiveTab] = useState<
    | "agent"
    | "pages"
    | "issues"
    | "fixes"
    | "eeat"
    | "links"
    | "status"
    | "visualization"
    | "integrations"
  >("agent");
  const [issueKey, setIssueKey] = useState(0);

  if (!canUseApi) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <p className="text-amber-700">A registered workspace account is required.</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <p className="text-red-600">Site not found in this workspace</p>
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
    setIssueKey((key) => key + 1);
    setActiveTab("issues");
    mutate();
  }

  const tabs = [
    { key: "agent", label: "💬 Agent" },
    { key: "pages", label: "Pages" },
    { key: "issues", label: "Issues" },
    { key: "fixes", label: "Fix Actions" },
    { key: "eeat", label: "🎓 E-E-A-T" },
    { key: "links", label: "🔗 Links" },
    { key: "status", label: "Status Codes" },
    { key: "visualization", label: "🗺️ Map" },
    { key: "integrations", label: "Integrations" },
  ] as const;

  return (
    <div className="min-h-screen bg-gray-50">
      <SiteHeader site={site} onAgentComplete={handleAgentComplete} />
      <main className="max-w-7xl mx-auto px-6 py-8">
        <StatCards site={site} />
        <div className="mt-8">
          <div className="border-b border-gray-200 mb-6 overflow-x-auto">
            <nav className="flex gap-6 min-w-max">
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
          {activeTab === "issues" && <IssuesPanel key={issueKey} siteId={id} site={site} />}
          {activeTab === "fixes" && <FixActionsPanel siteId={id} />}
          {activeTab === "eeat" && <EEATPanel siteId={id} />}
          {activeTab === "links" && <LinksPanel siteId={id} />}
          {activeTab === "status" && <StatusCodesPanel siteId={id} />}
          {activeTab === "visualization" && <VisualizationPanel siteId={id} />}
          {activeTab === "integrations" && <IntegrationsPanel siteId={id} />}
        </div>
      </main>
    </div>
  );
}
