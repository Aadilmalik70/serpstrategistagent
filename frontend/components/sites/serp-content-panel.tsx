"use client";

import { useState } from "react";
import useSWR from "swr";

import { apiFetch } from "@/lib/api";

type Opportunity = {
  id: string;
  page_id: string | null;
  opportunity_type: string;
  status: string;
  title: string;
  summary: string;
  target_query: string | null;
  target_path: string | null;
  priority_score: number;
  confidence_score: number;
  effort_score: number;
  evidence: Array<Record<string, unknown>>;
};

type Brief = {
  id: string;
  title: string;
  target_query: string | null;
  page_type: string;
  search_intent: string;
  outline: Array<{ heading: string; purpose: string }>;
  required_topics: string[];
  required_entities: string[];
  internal_link_targets: Array<{ path: string; anchor_text: string; reason: string }>;
  information_gain: string[];
  evidence: Array<Record<string, unknown>>;
  scores: Record<string, number>;
};

type Draft = {
  id: string;
  brief_id: string;
  action_id: string | null;
  status: string;
  title: string;
  meta_title: string;
  meta_description: string;
  body_markdown: string;
  generation_mode: string;
  word_count: number;
  version: number;
  quality_summary: { overall_score?: number; passed?: boolean; checks?: Array<{ label: string; passed: boolean; detail: string }> };
};

type Workspace = { opportunities: Opportunity[]; briefs: Brief[]; drafts: Draft[]; counts: Record<string, number> };

function scoreClass(score: number) {
  if (score >= 75) return "serp-content-score serp-content-score-high";
  if (score >= 50) return "serp-content-score serp-content-score-mid";
  return "serp-content-score serp-content-score-low";
}

export default function SerpContentPanel({ siteId }: { siteId: string }) {
  const { data, error, isLoading, mutate } = useSWR<Workspace>(`/sites/${siteId}/content`, (path: string) => apiFetch<Workspace>(path));
  const [selectedBrief, setSelectedBrief] = useState<string | null>(null);
  const [selectedDraft, setSelectedDraft] = useState<string | null>(null);
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("");

  if (isLoading) return <div className="site-panel-loading">Loading SERP Content workspace…</div>;
  if (error) return <div className="site-panel-error">SERP Content could not load. {error.message}</div>;
  if (!data) return null;

  const brief = data.briefs.find((item) => item.id === selectedBrief) || data.briefs[0];
  const draft = data.drafts.find((item) => item.id === selectedDraft) || data.drafts[0];
  const editorValue = selectedDraft ? body : (draft?.body_markdown ?? body);

  async function createBrief(opportunity: Opportunity) {
    setBusy(`brief:${opportunity.id}`);
    setMessage("");
    try {
      const created = await apiFetch<Brief>(`/sites/${siteId}/content/briefs`, { method: "POST", body: JSON.stringify({ opportunity_id: opportunity.id }) });
      setSelectedBrief(created.id);
      setMessage("Brief created from the opportunity evidence.");
      await mutate();
    } catch (requestError) { setMessage(requestError instanceof Error ? requestError.message : "Brief could not be created."); }
    finally { setBusy(null); }
  }

  async function generateDraft() {
    if (!brief) return;
    setBusy("generate");
    try {
      const created = await apiFetch<Draft>(`/content/briefs/${brief.id}/generate`, { method: "POST", body: JSON.stringify({ mode: "ai_assisted" }) });
      setSelectedDraft(created.id);
      setBody(created.body_markdown);
      setMessage(created.generation_mode === "ai_assisted" ? "AI-assisted draft generated. Review every claim before approval." : "Evidence scaffold generated because the AI provider was unavailable.");
      await mutate();
    } catch (requestError) { setMessage(requestError instanceof Error ? requestError.message : "Draft could not be generated."); }
    finally { setBusy(null); }
  }

  async function saveDraft() {
    if (!draft) return;
    setBusy("save");
    try {
      const saved = await apiFetch<Draft>(`/content/drafts/${draft.id}`, { method: "PUT", body: JSON.stringify({ title: draft.title, meta_title: draft.meta_title, meta_description: draft.meta_description, body_markdown: body }) });
      setBody(saved.body_markdown);
      setMessage(`Draft saved as version ${saved.version}.`);
      await mutate();
    } catch (requestError) { setMessage(requestError instanceof Error ? requestError.message : "Draft could not be saved."); }
    finally { setBusy(null); }
  }

  async function qualityCheck() {
    if (!draft) return;
    setBusy("quality");
    try {
      await apiFetch(`/content/drafts/${draft.id}/quality-check`, { method: "POST" });
      setMessage("Quality gates refreshed.");
      await mutate();
    } catch (requestError) { setMessage(requestError instanceof Error ? requestError.message : "Quality check failed."); }
    finally { setBusy(null); }
  }

  async function submitApproval() {
    if (!draft) return;
    setBusy("approve");
    try {
      await apiFetch(`/content/drafts/${draft.id}/submit-for-approval`, { method: "POST" });
      setMessage("Draft submitted to the governed Action Queue. Nothing was published.");
      await mutate();
    } catch (requestError) { setMessage(requestError instanceof Error ? requestError.message : "Draft could not be submitted."); }
    finally { setBusy(null); }
  }

  return (
    <div className="serp-content-workspace">
      <section className="serp-content-hero">
        <div>
          <p className="section-eyebrow">Create · SERP Content</p>
          <h2 className="serp-content-title">Turn search evidence into work that ships.</h2>
          <p className="serp-content-copy">Build a brief, draft against the evidence, run quality gates, and send only approved work to the Action Queue.</p>
        </div>
        <div className="serp-content-counts">
          <div><strong>{data.counts.opportunities || 0}</strong><span>opportunities</span></div>
          <div><strong>{data.counts.briefs || 0}</strong><span>briefs</span></div>
          <div><strong>{data.counts.awaiting_approval || 0}</strong><span>in approval</span></div>
        </div>
      </section>

      {message && <div className="serp-content-message">{message}</div>}

      <section className="serp-content-section">
        <div className="section-heading-row"><div><h3 className="section-title">Content opportunities</h3><p className="section-subtitle">Prioritized from Content Intelligence, Search Console, and AI citation gaps.</p></div></div>
        <div className="serp-content-opportunity-list">
          {data.opportunities.slice(0, 8).map((opportunity) => (
            <article className="serp-content-opportunity" key={opportunity.id}>
              <div className="serp-content-opportunity-main"><div className="serp-content-type">{opportunity.opportunity_type.replaceAll("_", " ")}</div><h4>{opportunity.title}</h4><p>{opportunity.summary}</p>{opportunity.target_query && <code>{opportunity.target_query}</code>}</div>
              <div className="serp-content-opportunity-side"><span className={scoreClass(opportunity.priority_score)}>P{opportunity.priority_score}</span><small>Confidence {opportunity.confidence_score}</small><button type="button" className="button button-secondary" onClick={() => void createBrief(opportunity)} disabled={busy !== null}>Create brief <span>→</span></button></div>
            </article>
          ))}
          {!data.opportunities.length && <p className="panel-empty">Run Content Intelligence and Search Console sync first to populate evidence-backed opportunities.</p>}
        </div>
      </section>

      <section className="serp-content-builder">
        <div className="serp-content-brief-column">
          <div className="section-heading-row"><div><h3 className="section-title">Briefs</h3><p className="section-subtitle">The evidence and plan behind each draft.</p></div></div>
          <div className="serp-content-list">
            {data.briefs.map((item) => <button type="button" className={`serp-content-list-item ${brief?.id === item.id ? "is-selected" : ""}`} key={item.id} onClick={() => setSelectedBrief(item.id)}><span>{item.title}</span><small>{item.target_query || item.page_type}</small></button>)}
            {!data.briefs.length && <p className="panel-empty">Create a brief from an opportunity above.</p>}
          </div>
          {brief && <div className="serp-content-brief-card"><div className="serp-content-card-label">Selected brief</div><h3>{brief.title}</h3><dl><div><dt>Intent</dt><dd>{brief.search_intent}</dd></div><div><dt>Page type</dt><dd>{brief.page_type}</dd></div><div><dt>Priority</dt><dd>{brief.scores.priority ?? "—"}</dd></div></dl><h4>Outline</h4><ol>{brief.outline.map((item) => <li key={item.heading}><strong>{item.heading}</strong><small>{item.purpose}</small></li>)}</ol><h4>Information gain</h4><ul>{brief.information_gain.map((item) => <li key={item}>{item}</li>)}</ul><button type="button" className="button button-primary button-wide" onClick={() => void generateDraft()} disabled={busy !== null}>Generate draft <span>✦</span></button></div>}
        </div>
        <div className="serp-content-draft-column">
          <div className="section-heading-row"><div><h3 className="section-title">Draft workspace</h3><p className="section-subtitle">Editable Markdown with review gates before approval.</p></div>{draft && <span className="serp-content-status">{draft.status.replaceAll("_", " ")}</span>}</div>
          {data.drafts.length > 1 && <div className="serp-content-draft-picker">{data.drafts.map((item) => <button type="button" className={draft?.id === item.id ? "is-selected" : ""} key={item.id} onClick={() => { setSelectedDraft(item.id); setBody(item.body_markdown); }}>{item.title}</button>)}</div>}
          {draft ? <><div className="serp-content-draft-meta"><div><span>Mode</span><strong>{draft.generation_mode.replaceAll("_", " ")}</strong></div><div><span>Words</span><strong>{draft.word_count}</strong></div><div><span>Quality</span><strong>{draft.quality_summary.overall_score ?? "—"}/100</strong></div></div><textarea className="serp-content-editor" value={editorValue} onChange={(event) => { setSelectedDraft(draft.id); setBody(event.target.value); }} aria-label="Content draft Markdown" /><div className="serp-content-actions"><button type="button" className="button button-secondary" onClick={() => void saveDraft()} disabled={busy !== null}>Save version</button><button type="button" className="button button-secondary" onClick={() => void qualityCheck()} disabled={busy !== null}>Run quality gates</button><button type="button" className="button button-primary" onClick={() => void submitApproval()} disabled={busy !== null}>Send to Action Queue <span>↗</span></button></div>{draft.quality_summary.checks && <div className="serp-content-checks">{draft.quality_summary.checks.map((check) => <div key={check.label} className={check.passed ? "check-passed" : "check-failed"}><span>{check.passed ? "✓" : "!"}</span><div><strong>{check.label}</strong><small>{check.detail}</small></div></div>)}</div>}</> : <div className="serp-content-empty"><strong>Your first draft is waiting.</strong><span>Select an opportunity, create a brief, and generate a reviewable draft.</span></div>}
        </div>
      </section>
    </div>
  );
}
