"use client";

import Link from "next/link";
import { useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface SiteHeaderProps {
  site: {
    id: string;
    name: string;
    domain: string;
  };
  onAgentComplete?: () => void;
}

export default function SiteHeader({ site, onAgentComplete }: SiteHeaderProps) {
  const [running, setRunning] = useState(false);

  async function handleRunAgent() {
    setRunning(true);
    try {
      const res = await fetch(`${API_URL}/agent/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ site_id: site.id }),
      });
      if (!res.ok) throw new Error("Failed to start agent");
      const data = await res.json();

      // Poll for completion
      const pollInterval = setInterval(async () => {
        const statusRes = await fetch(`${API_URL}/agent/run/${data.run_id}`);
        const status = await statusRes.json();
        if (status.status === "completed" || status.status === "failed") {
          clearInterval(pollInterval);
          setRunning(false);
          onAgentComplete?.();
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
