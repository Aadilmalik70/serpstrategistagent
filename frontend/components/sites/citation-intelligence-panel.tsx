"use client";

import { useState } from "react";
import useSWR from "swr";

import { apiFetch, OperatorApiError } from "@/lib/api";

type PromptSet = {
  id: string;
  name: string;
  brand_terms: string[];
  competitor_terms: string[];
  prompts: string[];
  providers: string[];
};

type Dashboard = {
  prompt_sets: PromptSet[];
  latest_scan: {
    id: string;
    status: string;
    prompt_count: number;
    result_count: number;
    visibility_score: number;
    mention_rate: number;
    citation_rate: number;
  } | null;
  results: Array<{
    id: string;
    provider: string;
    prompt: string;
    answer_excerpt: string;
    brand_mentioned: boolean;
    cited_urls: string[];
    competitor_mentions: string[];
  }>;
  gaps: Array<{
    id: string;
    gap_type: string;
    prompt: string;
    competitor: string | null;
    priority_score: number;
    confidence_score: number;
    action_id: string | null;
  }>;
  provider_notes: string[];
};

export default function CitationIntelligencePanel({ siteId }: { siteId: string }) {
  const { data, error, mutate } = useSWR<Dashboard>(
    `/sites/${siteId}/citation-intelligence`,
    apiFetch,
  );
  const [brand, setBrand] = useState("SERP Strategists");
  const [competitors, setCompetitors] = useState("");
  const [prompts, setPrompts] = useState("What are the best AI SEO tools?\nHow can a SaaS company improve organic visibility?");
  const [answer, setAnswer] = useState("");
  const [citedUrls, setCitedUrls] = useState("");
  const [promptSetId, setPromptSetId] = useState("");
  const [scanId, setScanId] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  async function createPromptSet() {
    setBusy(true);
    setMessage("");
    try {
      const created = await apiFetch<PromptSet>(`/sites/${siteId}/citation-intelligence/prompt-sets`, {
        method: "POST",
        body: JSON.stringify({
          name: "Default AI visibility prompts",
          brand_terms: brand.split(",").map((item) => item.trim()).filter(Boolean),
          competitor_terms: competitors.split(",").map((item) => item.trim()).filter(Boolean),
          prompts: prompts.split("\n").map((item) => item.trim()).filter(Boolean),
          providers: ["manual"],
        }),
      });
      setPromptSetId(created.id);
      setMessage("Prompt set created. Add provider results below, then finalize the scan.");
      await mutate();
    } catch (requestError) {
      setMessage(requestError instanceof OperatorApiError ? requestError.message : "Prompt set could not be created.");
    } finally {
      setBusy(false);
    }
  }

  async function startScan() {
    const selected = promptSetId || data?.prompt_sets[0]?.id;
    if (!selected) {
      setMessage("Create a prompt set first.");
      return;
    }
    setBusy(true);
    try {
      const scan = await apiFetch<{ id: string }>(`/sites/${siteId}/citation-intelligence/scans`, {
        method: "POST",
        body: JSON.stringify({ prompt_set_id: selected }),
      });
      setPromptSetId(selected);
      setScanId(scan.id);
      setMessage("Scan queued. This first slice uses the manual/provider-ingest boundary; no browser scraping is performed.");
      await mutate();
    } catch (requestError) {
      setMessage(requestError instanceof OperatorApiError ? requestError.message : "Citation scan could not be started.");
    } finally {
      setBusy(false);
    }
  }

  async function ingestAndFinalize() {
    const scan = scanId || data?.latest_scan?.id;
    const selected = data?.prompt_sets.find((item) => item.id === promptSetId) || data?.prompt_sets[0];
    const prompt = selected?.prompts[0];
    if (!scan || !selected || !prompt) {
      setMessage("Start a scan and select a prompt set first.");
      return;
    }
    setBusy(true);
    try {
      await apiFetch(`/sites/${siteId}/citation-intelligence/scans/${scan}/results`, {
        method: "POST",
        body: JSON.stringify({
          provider: "manual",
          prompt,
          answer,
          cited_urls: citedUrls.split("\n").map((item) => item.trim()).filter(Boolean),
        }),
      });
      await apiFetch(`/sites/${siteId}/citation-intelligence/scans/${scan}/finalize`, { method: "POST" });
      setMessage("Result ingested and citation gaps recalculated. Recommendations remain simulation-only.");
      await mutate();
    } catch (requestError) {
      setMessage(requestError instanceof OperatorApiError ? requestError.message : "Provider result could not be ingested.");
    } finally {
      setBusy(false);
    }
  }

  if (error) return <div className="rounded-[20px] border border-red-200 bg-red-50 p-6 text-sm text-red-700">Citation intelligence is unavailable.</div>;
  if (!data) return <div className="h-64 animate-pulse rounded-[20px] bg-gray-200" />;

  return (
    <div className="space-y-5">
      <section className="rounded-[20px] border border-gray-200 bg-white p-5 sm:p-6">
        <p className="text-xs font-semibold uppercase tracking-[0.14em] text-gray-500">Phase 8 · AI citation intelligence</p>
        <div className="mt-2 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <h3 className="text-2xl font-semibold tracking-[-0.035em]">Measure how AI answers discover you</h3>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-gray-600">Create reusable prompt sets, ingest official-provider results, and turn missing mentions or citations into governed recommendations.</p>
          </div>
          <div className="flex gap-2">
            <button type="button" onClick={createPromptSet} disabled={busy} className="min-h-10 rounded-full border border-gray-300 px-4 text-sm font-semibold disabled:opacity-50">Create prompts</button>
            <button type="button" onClick={startScan} disabled={busy || data.prompt_sets.length === 0} className="min-h-10 rounded-full bg-[#202020] px-4 text-sm font-semibold text-white disabled:opacity-50">Start scan</button>
          </div>
        </div>
        <div className="mt-5 grid gap-3 md:grid-cols-3">
          <input value={brand} onChange={(event) => setBrand(event.target.value)} placeholder="Brand terms, comma separated" className="rounded-xl border border-gray-200 px-3 py-2 text-sm" />
          <input value={competitors} onChange={(event) => setCompetitors(event.target.value)} placeholder="Competitors, comma separated" className="rounded-xl border border-gray-200 px-3 py-2 text-sm" />
          <textarea value={prompts} onChange={(event) => setPrompts(event.target.value)} rows={3} placeholder="One prompt per line" className="rounded-xl border border-gray-200 px-3 py-2 text-sm md:col-span-1" />
        </div>
        {message && <p className="mt-4 text-sm text-gray-700">{message}</p>}
      </section>

      {data.latest_scan && (
        <section className="grid grid-cols-2 gap-3 lg:grid-cols-5">
          {[["Visibility", data.latest_scan.visibility_score], ["Mention rate", `${Math.round(data.latest_scan.mention_rate * 100)}%`], ["Citation rate", `${Math.round(data.latest_scan.citation_rate * 100)}%`], ["Results", data.latest_scan.result_count], ["Gaps", data.gaps.length]].map(([label, value]) => <div key={String(label)} className="rounded-2xl border border-gray-200 bg-white p-4"><p className="text-xs text-gray-500">{label}</p><p className="mt-2 text-2xl font-semibold text-gray-950">{value}</p></div>)}
        </section>
      )}

      <section className="grid gap-5 lg:grid-cols-2">
        <div className="rounded-[20px] border border-gray-200 bg-white p-5">
          <h4 className="text-lg font-semibold">Manual/provider result test</h4>
          <p className="mt-1 text-xs leading-5 text-gray-500">Use this only to validate the contract until an official provider worker is enabled.</p>
          <textarea value={answer} onChange={(event) => setAnswer(event.target.value)} rows={5} placeholder="Paste the provider answer here" className="mt-4 w-full rounded-xl border border-gray-200 px-3 py-2 text-sm" />
          <textarea value={citedUrls} onChange={(event) => setCitedUrls(event.target.value)} rows={3} placeholder="One cited URL per line" className="mt-3 w-full rounded-xl border border-gray-200 px-3 py-2 text-sm" />
          <button type="button" onClick={ingestAndFinalize} disabled={busy || !answer.trim()} className="mt-3 min-h-10 rounded-full bg-[#202020] px-4 text-sm font-semibold text-white disabled:opacity-50">Ingest and finalize</button>
        </div>
        <div className="rounded-[20px] border border-gray-200 bg-white p-5">
          <h4 className="text-lg font-semibold">Citation-gap queue</h4>
          <div className="mt-4 divide-y divide-gray-100">{data.gaps.slice(0, 8).map((gap) => <div key={gap.id} className="py-3"><div className="flex items-center justify-between gap-3"><p className="text-sm font-medium text-gray-950">{gap.gap_type.replaceAll("_", " ")}</p><span className="rounded-full bg-orange-50 px-2 py-1 text-xs font-semibold text-orange-700">{gap.priority_score}</span></div><p className="mt-1 text-xs text-gray-500">{gap.prompt} · confidence {gap.confidence_score}</p></div>)}{data.gaps.length === 0 && <p className="py-4 text-sm text-gray-500">No citation gaps in the latest completed scan.</p>}</div>
        </div>
      </section>

      <section className="rounded-[20px] border border-gray-200 bg-white p-5"><h4 className="text-lg font-semibold">Provider boundary</h4><ul className="mt-3 space-y-2 text-sm leading-6 text-gray-600">{data.provider_notes.map((note) => <li key={note}>• {note}</li>)}</ul></section>
    </div>
  );
}
