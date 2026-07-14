interface StatCardsProps {
  site: {
    page_count: number;
    issue_count: number;
    status: string;
    updated_at: string;
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
}

const gradeColors: Record<string, string> = {
  "A+": "text-green-600",
  A: "text-green-600",
  B: "text-green-500",
  C: "text-yellow-600",
  D: "text-orange-600",
  F: "text-red-600",
};

export default function StatCards({ site }: StatCardsProps) {
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
      <div className="rounded-lg border border-gray-200 bg-white p-5">
        <p className="text-sm text-gray-500">Health Score</p>
        {site.health_score !== null ? (
          <div className="mt-1 flex items-baseline gap-2">
            <p className={`text-2xl font-bold ${gradeColors[site.health_grade || "F"] || "text-gray-900"}`}>
              {site.health_score}/100
            </p>
            <span className={`text-lg font-semibold ${gradeColors[site.health_grade || "F"] || "text-gray-500"}`}>
              ({site.health_grade})
            </span>
          </div>
        ) : (
          <div className="mt-1">
            <p className="text-2xl font-bold text-gray-400">—</p>
            <p className="mt-1 text-xs text-gray-400">Available after crawl and analysis</p>
          </div>
        )}
      </div>
      <div className="rounded-lg border border-gray-200 bg-white p-5">
        <p className="text-sm text-gray-500">Pages Discovered</p>
        <p className="mt-1 text-2xl font-bold">{site.page_count}</p>
      </div>
      <div className="rounded-lg border border-gray-200 bg-white p-5">
        <p className="text-sm text-gray-500">Issues Found</p>
        <p className="mt-1 text-2xl font-bold">
          {site.issue_count || site.latest_run?.issues_found || "—"}
        </p>
      </div>
      <div className="rounded-lg border border-gray-200 bg-white p-5">
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm text-gray-500">Status</p>
          <span className="rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700">
            First-party crawler
          </span>
        </div>
        <p className="mt-1 text-2xl font-bold capitalize">{site.status.replaceAll("_", " ")}</p>
        {site.latest_run?.completed_at && (
          <p className="mt-1 text-xs text-gray-400">
            Last analysis: {new Date(site.latest_run.completed_at).toLocaleString()}
          </p>
        )}
      </div>
    </div>
  );
}
