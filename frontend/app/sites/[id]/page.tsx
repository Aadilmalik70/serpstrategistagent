"use client";

import { use, useState } from "react";
import { useSession } from "next-auth/react";
import useSWR from "swr";

import OperatorHeader from "@/components/dashboard/operator-header";
import AgentChatPanel from "@/components/sites/agent-chat-panel";
import CitationIntelligencePanel from "@/components/sites/citation-intelligence-panel";
import ContentIntelligencePanel from "@/components/sites/content-intelligence-panel";
import EEATPanel from "@/components/sites/eeat-panel";
import IntegrationsPanel from "@/components/sites/integrations-panel";
import IssuesPanel from "@/components/sites/issues-panel";
import LinksPanel from "@/components/sites/links-panel";
import PagesTable from "@/components/sites/pages-table";
import SearchPerformancePanel from "@/components/sites/search-performance-panel";
import SerpContentPanel from "@/components/sites/serp-content-panel";
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
  tech_stack?: string;
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

type TabKey =
  | "agent" | "pages" | "issues" | "eeat" | "links" | "status"
  | "visualization" | "integrations" | "search" | "content" | "citation" | "serp-content";

export default function SiteDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data: session } = useSession();
  const canUseApi = Boolean(session?.accessToken && session.workspaceId);
  const { data: site, error, mutate } = useSWR<SiteDetail>(canUseApi ? `/sites/${id}` : null, (path: string) => apiFetch<SiteDetail>(path));
  const [activeTab, setActiveTab] = useState<TabKey>("agent");
  const [issueKey, setIssueKey] = useState(0);
  const [pageKey, setPageKey] = useState(0);

  if (!canUseApi) return <div className="site-detail-page flex min-h-screen items-center justify-center"><p className="site-route-message">A registered workspace account is required.</p></div>;
  if (error) return <div className="site-detail-page flex min-h-screen items-center justify-center"><p className="site-route-message site-route-error">Site not found in this workspace</p></div>;
  if (!site) return <div className="site-detail-page flex min-h-screen items-center justify-center"><div className="site-route-loader h-8 w-8 animate-spin rounded-full" /></div>;

  function handleAgentComplete() { setIssueKey((key) => key + 1); setActiveTab("issues"); void mutate(); }
  function handleCrawlComplete() { setPageKey((key) => key + 1); setActiveTab("pages"); void mutate(); }

  const tabs: Array<{ key: TabKey; label: string }> = [
    { key: "agent", label: "💬 Agent" }, { key: "pages", label: "Pages" }, { key: "issues", label: "Technical Findings" },
    { key: "search", label: "Search Opportunities" }, { key: "content", label: "Content Intelligence" }, { key: "serp-content", label: "✎ SERP Content" },
    { key: "citation", label: "AI Citations" }, { key: "eeat", label: "🎓 E-E-A-T" }, { key: "links", label: "🔗 Links" },
    { key: "status", label: "Status Codes" }, { key: "visualization", label: "🗺️ Map" }, { key: "integrations", label: "Integrations" },
  ];

  return (
    <div className="site-detail-page min-h-screen">
      <OperatorHeader />
      <SiteHeader site={site} onAgentComplete={handleAgentComplete} onCrawlComplete={handleCrawlComplete} />
      <main className="site-detail-main">
        <StatCards site={site} />
        <div className="mt-8">
          <div className="site-tab-shell overflow-x-auto"><nav className="site-tab-list min-w-max">
            {tabs.map((tab) => <button type="button" key={tab.key} onClick={() => setActiveTab(tab.key)} className={`site-tab ${activeTab === tab.key ? "is-active" : ""}`}>{tab.label}</button>)}
          </nav></div>
          {activeTab === "agent" && <AgentChatPanel siteId={id} />}
          {activeTab === "pages" && <PagesTable key={pageKey} siteId={id} />}
          {activeTab === "issues" && <IssuesPanel key={issueKey} siteId={id} site={site} />}
          {activeTab === "search" && <SearchPerformancePanel siteId={id} />}
          {activeTab === "content" && <ContentIntelligencePanel siteId={id} />}
          {activeTab === "serp-content" && <SerpContentPanel siteId={id} />}
          {activeTab === "citation" && <CitationIntelligencePanel siteId={id} />}
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
