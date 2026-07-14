"use client";

import Link from "next/link";
import { useState } from "react";

import { apiFetch, OperatorApiError } from "@/lib/api";

interface SiteHeaderProps {
  site: {
    id: string;
    name: string;
    domain: string;
    page_count: number;
    status: string;
  };
  onAgentComplete?: () => void;
  onCrawlComplete?: () => void;
}

type AgentRun = { run_id: string; status: string };
type AgentStatus = {
  status: string;
  summary?: string | null;
  error?: string | null;
  pages_analyzed?: number;
  meta?: { phase?: string; crawl_job_id?: string };
};
type CrawlStart = { job_id: string; status: string; reused?: boolean };
type CrawlStatus = {
  status: string;
  pages_discovered: number;
  pages_crawled: number;
  errors: number;
  error: string | null;
};

const TERMINAL_CRAWL_STATES = new Set(["completed", "failed", "cancelled"]);

export default function SiteHeader({ site, onAgentComplete, onCrawlComplete }: SiteHeaderProps) {
  const [runningAgent, setRunningAgent] = useState(false);
  const [runningCrawl, setRunningCrawl] = useState(false);
  const [statusMessage, setStatusMessage] = useState("");
  const [statusError, setStatusError] = useState(false);

  async function waitForCrawl(jobId: string): Promise<boolean> {
    for (let attempt = 0; attempt < 240; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 1250));
      const crawl = await apiFetch<CrawlStatus>(`/crawl/${jobId}`);
      setStatusMessage(
        crawl.status === "completed"
          ? `Crawl completed: ${crawl.pages_crawled} pages.`
          : `Crawling: ${crawl.pages_crawled}/${Math.max(crawl.pages_discovered, crawl.pages_crawled)} pages`,
      );
      if (TERMINAL_CRAWL_STATES.has(crawl.status)) {
        if (crawl.status === "completed" && crawl.pages_crawled > 0) {
          setStatusError(false);
          onCrawlComplete?.();
          return true;
        }
        setStatusError(true);
        setStatusMessage(crawl.error || "The crawl failed before any page could be stored.");
        return false;
      }
    }
    setStatusError(true);
    setStatusMessage("The crawl is still running. Refresh the page to check its latest state.");
    return false;
  }

  async function startCrawl(): Promise<boolean> {
    if (runningCrawl) return false;
    setRunningCrawl(true);
    setStatusError(false);
    setStatusMessage("Starting first-party crawl…");
    try {
      const crawl = await apiFetch<CrawlStart>("/crawl/site", {
        method: "POST",
        body: JSON.stringify({ site_id: site.id }),
      });
      return await waitForCrawl(crawl.job_id);
    } catch (error) {
      setStatusError(true);
      setStatusMessage(
        error instanceof OperatorApiError ? error.message : "The crawl could not be started.",
      );
      return false;
    } finally {
      setRunningCrawl(false);
    }
  }

  async function handleRunAgent() {
    if (runningAgent || runningCrawl) return;
    setRunningAgent(true);
    setStatusError(false);
    setStatusMessage(site.page_count > 0 ? "Starting analysis…" : "Starting crawl before analysis…");

    try {
      const data = await apiFetch<AgentRun>("/agent/run", {
        method: "POST",
        body: JSON.stringify({ site_id: site.id }),
      });

      for (let attempt = 0; attempt < 480; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 1250));
        const run = await apiFetch<AgentStatus>(`/agent/run/${data.run_id}`);

        if (run.status === "crawling") {
          setStatusMessage(run.summary || "Crawling the site before analysis…");
          continue;
        }
        if (run.status === "running") {
          setStatusMessage(run.summary || "Analyzing crawled pages…");
          continue;
        }
        if (run.status === "completed") {
          if ((run.pages_analyzed ?? 0) < 1) {
            setStatusError(true);
            setStatusMessage(run.summary || "No pages were available for analysis.");
            return;
          }
          setStatusMessage(run.summary || "Agent analysis completed.");
          onAgentComplete?.();
          onCrawlComplete?.();
          return;
        }
        if (run.status === "failed") {
          setStatusError(true);
          setStatusMessage(run.error || run.summary || "Agent analysis failed.");
          return;
        }
      }

      setStatusError(true);
      setStatusMessage("The analysis is still running. Refresh to check the latest status.");
    } catch (error) {
      setStatusError(true);
      setStatusMessage(
        error instanceof OperatorApiError ? error.message : "The agent could not be started.",
      );
    } finally {
      setRunningAgent(false);
    }
  }

  return (
    <header className="border-b border-gray-200 bg-white px-4 py-4 sm:px-6">
      <div className="mx-auto flex max-w-7xl flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-4">
          <Link href="/" className="text-sm text-gray-500 hover:text-gray-700">
            ← Back
          </Link>
          <div>
            <h1 className="text-xl font-bold">{site.name}</h1>
            <p className="text-sm text-gray-500">{site.domain}</p>
          </div>
        </div>

        <div className="flex flex-col items-stretch gap-2 sm:items-end">
          <div className="flex flex-wrap gap-2 sm:justify-end">
            <button
              type="button"
              onClick={() => void startCrawl()}
              disabled={runningCrawl || runningAgent}
              className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-800 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {runningCrawl ? "Crawling…" : site.page_count > 0 ? "Recrawl Site" : "Crawl Site"}
            </button>
            <button
              type="button"
              onClick={handleRunAgent}
              disabled={runningAgent || runningCrawl}
              className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-gray-100 disabled:text-gray-400"
            >
              {runningAgent ? "Working…" : "Run Agent"}
            </button>
          </div>
          {statusMessage && (
            <p className={`max-w-md text-xs ${statusError ? "text-red-600" : "text-gray-500"}`}>
              {statusMessage}
            </p>
          )}
        </div>
      </div>
    </header>
  );
}
