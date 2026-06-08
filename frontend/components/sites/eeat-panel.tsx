"use client";

import useSWR from "swr";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function fetcher(url: string) {
  const res = await fetch(url);
  if (!res.ok) throw new Error("Failed to fetch");
  return res.json();
}

interface EEATProps {
  siteId: string;
}

interface Signal {
  count: number;
  total: number;
  pct: number;
}

interface EEATData {
  score: number;
  total_pages: number;
  signals: Record<string, Signal>;
  external_citations_total: number;
  avg_citations_per_page: number;
}

const signalLabels: Record<string, { icon: string; label: string }> = {
  author_attribution: { icon: "✍️", label: "Author Attribution" },
  structured_data: { icon: "📊", label: "Structured Data" },
  external_links: { icon: "🔗", label: "External Links" },
  og_tags: { icon: "🏷️", label: "Open Graph Tags" },
  https_secure: { icon: "🔒", label: "HTTPS Secure" },
  sufficient_content: { icon: "📝", label: "Sufficient Content" },
};

function ScoreRing({ score }: { score: number }) {
  const radius = 45;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (score / 100) * circumference;
  const color =
    score >= 80 ? "#10b981" : score >= 60 ? "#f59e0b" : "#ef4444";

  return (
    <div className="relative w-28 h-28">
      <svg className="w-full h-full -rotate-90" viewBox="0 0 100 100">
        <circle
          cx="50" cy="50" r={radius}
          fill="none" stroke="#e5e7eb" strokeWidth="8"
        />
        <circle
          cx="50" cy="50" r={radius}
          fill="none" stroke={color} strokeWidth="8"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-2xl font-bold" style={{ color }}>{score}</span>
        <span className="text-xs text-gray-500">/ 100</span>
      </div>
    </div>
  );
}

export default function EEATPanel({ siteId }: EEATProps) {
  const { data, isLoading } = useSWR<EEATData>(
    `${API_URL}/sites/${siteId}/eeat`,
    fetcher
  );

  if (isLoading) {
    return <div className="h-64 bg-gray-200 rounded-lg animate-pulse" />;
  }

  if (!data || data.total_pages === 0) {
    return (
      <div className="text-center py-12 text-gray-500">
        <p>No E-E-A-T data available. Run a crawl first.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold">🎓 E-E-A-T Analysis</h3>
          <p className="text-sm text-gray-500">
            Experience, Expertise, Authoritativeness, and Trust signals
          </p>
        </div>
      </div>

      {/* Score cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="bg-white rounded-lg border border-gray-200 p-5 flex flex-col items-center">
          <p className="text-sm text-gray-500 mb-2">Overall E-E-A-T Score</p>
          <ScoreRing score={data.score} />
        </div>
        <div className="bg-white rounded-lg border border-gray-200 p-5 text-center">
          <p className="text-sm text-gray-500">Pages with Schema</p>
          <p className="text-3xl font-bold mt-2">{data.signals.structured_data?.count ?? 0}</p>
          <p className="text-xs text-gray-400 mt-1">
            {data.signals.structured_data?.pct ?? 0}% of pages
          </p>
        </div>
        <div className="bg-white rounded-lg border border-gray-200 p-5 text-center">
          <p className="text-sm text-gray-500">Pages with Author Info</p>
          <p className="text-3xl font-bold mt-2">{data.signals.author_attribution?.count ?? 0}</p>
          <p className="text-xs text-gray-400 mt-1">
            {data.signals.author_attribution?.pct ?? 0}% of pages
          </p>
        </div>
        <div className="bg-white rounded-lg border border-gray-200 p-5 text-center">
          <p className="text-sm text-gray-500">External Citations</p>
          <p className="text-3xl font-bold mt-2">{data.external_citations_total}</p>
          <p className="text-xs text-gray-400 mt-1">
            Avg {data.avg_citations_per_page} per page
          </p>
        </div>
      </div>

      {/* Trust signals breakdown */}
      <div className="bg-white rounded-lg border border-gray-200 p-5">
        <h4 className="font-medium mb-4">Trust Signals Breakdown</h4>
        <div className="space-y-3">
          {Object.entries(data.signals).map(([key, signal]) => {
            const meta = signalLabels[key] || { icon: "📋", label: key };
            return (
              <div key={key} className="flex items-center gap-3">
                <span className="text-lg">{meta.icon}</span>
                <div className="flex-1">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-sm font-medium">{meta.label}</span>
                    <span className="text-sm text-gray-500">
                      {signal.count}/{signal.total} ({signal.pct}%)
                    </span>
                  </div>
                  <div className="w-full bg-gray-200 rounded-full h-2">
                    <div
                      className="h-2 rounded-full transition-all"
                      style={{
                        width: `${signal.pct}%`,
                        backgroundColor:
                          signal.pct >= 80
                            ? "#10b981"
                            : signal.pct >= 50
                              ? "#f59e0b"
                              : "#ef4444",
                      }}
                    />
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
