"use client";

import { useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface CrawlProgressProps {
  jobId: string;
  onComplete: () => void;
}

interface CrawlStatus {
  status: string;
  pages_discovered: number;
  pages_crawled: number;
  errors: number;
}

export default function CrawlProgress({ jobId, onComplete }: CrawlProgressProps) {
  const [status, setStatus] = useState<CrawlStatus | null>(null);

  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`${API_URL}/crawl/${jobId}`);
        if (res.ok) {
          const data = await res.json();
          setStatus(data);
          if (data.status === "completed" || data.status === "failed") {
            clearInterval(interval);
            if (data.status === "completed") {
              setTimeout(onComplete, 1000);
            }
          }
        }
      } catch {
        // Silently retry on network errors
      }
    }, 2000);

    return () => clearInterval(interval);
  }, [jobId, onComplete]);

  const progress = status
    ? status.pages_discovered > 0
      ? Math.round((status.pages_crawled / status.pages_discovered) * 100)
      : 0
    : 0;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold mb-2">Crawling your site...</h2>
        <p className="text-gray-600 text-sm">
          Discovering pages and extracting metadata. This may take a few minutes.
        </p>
      </div>

      {/* Progress bar */}
      <div>
        <div className="flex justify-between text-sm text-gray-600 mb-1">
          <span>
            {status?.pages_crawled || 0} / {status?.pages_discovered || "?"} pages
          </span>
          <span>{progress}%</span>
        </div>
        <div className="w-full bg-gray-200 rounded-full h-2">
          <div
            className="bg-blue-600 h-2 rounded-full transition-all duration-500"
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>

      {status?.errors ? (
        <p className="text-sm text-yellow-600">
          {status.errors} page(s) had errors (skipped)
        </p>
      ) : null}

      {status?.status === "failed" && (
        <p className="text-sm text-red-600">
          Crawl failed. Please try again from the site detail page.
        </p>
      )}
    </div>
  );
}
