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
    <div className="site-stat-strip">
      <div className="site-stat-card site-stat-card-featured">
        <div className="site-stat-heading"><p>Health score</p><span className="stat-status">Live</span></div>
        {site.health_score !== null ? (
          <div className="stat-value-row">
            <p className={`stat-value ${gradeColors[site.health_grade || "F"] || "text-gray-900"}`}>
              {site.health_score}/100
            </p>
            <span className="stat-grade">{site.health_grade}</span>
          </div>
        ) : (
          <div className="stat-value-row">
            <p className="stat-value stat-value-muted">—</p>
            <span className="stat-context">Awaiting analysis</span>
          </div>
        )}
      </div>
      <div className="site-stat-card">
        <div className="site-stat-heading"><p>Pages discovered</p><span className="stat-icon">▤</span></div>
        <p className="stat-value">{site.page_count}</p>
        <p className="stat-context">From latest crawl</p>
      </div>
      <div className="site-stat-card">
        <div className="site-stat-heading"><p>Open findings</p><span className="stat-icon stat-icon-alert">!</span></div>
        <p className="stat-value">
          {site.issue_count || site.latest_run?.issues_found || "—"}
        </p>
        <p className="stat-context">Technical and content signals</p>
      </div>
      <div className="site-stat-card">
        <div className="site-stat-heading"><p>Workspace status</p><span className="stat-status stat-status-green">● Ready</span></div>
        <p className="stat-value stat-value-status">{site.status.replaceAll("_", " ")}</p>
        <p className="stat-context">{site.latest_run?.completed_at ? `Last run ${new Date(site.latest_run.completed_at).toLocaleDateString()}` : "Ready for first run"}</p>
      </div>
    </div>
  );
}
