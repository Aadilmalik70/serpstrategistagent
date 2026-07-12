"use client";

import Link from "next/link";
import { useState } from "react";

import { apiFetch } from "@/lib/api";

interface SiteHeaderProps {
  site: {
    id: string;
    name: string;
    domain: string;
  };
  onAgentComplete?: () => void;
}

type AgentRun = { run_id: string };
type AgentStatus = { status: string };

export default function SiteHeader({ site, onAgentComplete }: SiteHeaderProps) {
  const [running, setRunning] = useState(false);

  async function handleRunAgent() {
    setRunning(true);
    try {
      const data = await apiFetch<AgentRun>("/agent/run", {
        method: "POST",
        body: JSON.stringify({ site_id: site.id }),
      });

      const pollInterval = window.setInterval(async () => {
        try {
          const run = await apiFetch<AgentStatus>(`/agent/run/${data.run_id}`);
          if (run.status === "completed" || run.status === "failed") {
            window.clearInterval(pollInterval);
            setRunning(false);
            onAgentComplete?.();
          }
        } catch {
          window.clearInterval(pollInterval);
          setRunning(false);
        }
      }, 1000);
    } catch {
      setRunning(false);
    }
  }

  return (
    <header className="bg-white border-b border-gray-200 px-6 py-4">
      <div className="max-w-7xl mx-auto flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link href="/" className="text-sm text-gray-500 hover:text-gray-700">
            ← Back
          </Link>
          <div>
            <h1 className="text-xl font-bold">{site.name}</h1>
            <p className="text-sm text-gray-500">{site.domain}</p>
          </div>
        </div>
        <button
          onClick={handleRunAgent}
          disabled={running}
          className={`px-4 py-2 rounded-md text-sm font-medium ${
            running
              ? "bg-gray-100 text-gray-400 cursor-not-allowed"
              : "bg-blue-600 text-white hover:bg-blue-700"
          }`}
        >
          {running ? "Analyzing..." : "Run Agent"}
        </button>
      </div>
    </header>
  );
}
