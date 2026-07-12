"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";

import { apiFetch, OperatorApiError } from "@/lib/api";

type GoogleConnection = {
  status: string;
  google_email: string | null;
  scopes: string[];
  gsc_property: string | null;
  ga4_property_id: string | null;
  ga4_property_name: string | null;
  baseline_status: string;
  baseline_summary: Record<string, unknown>;
  last_synced_at: string | null;
  connected_at: string | null;
  last_refreshed_at: string | null;
  last_error: string | null;
};

type PropertyOption = {
  id: string;
  name: string;
  type: string;
  permission_level: string | null;
};

type PropertyCatalog = {
  gsc_properties: PropertyOption[];
  ga4_properties: PropertyOption[];
};

type OAuthStart = { authorization_url: string };

function metric(summary: Record<string, unknown>, source: string, key: string) {
  const sourceValue = summary[source];
  if (!sourceValue || typeof sourceValue !== "object") return null;
  const value = (sourceValue as Record<string, unknown>)[key];
  return typeof value === "number" ? value : null;
}

export default function GoogleDataStep({ onReady }: { onReady?: (connection: GoogleConnection) => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [gscOverride, setGscOverride] = useState<string | null>(null);
  const [ga4Override, setGa4Override] = useState<string | null>(null);

  const {
    data: connection,
    mutate: mutateConnection,
    isLoading,
  } = useSWR<GoogleConnection>("/integrations/google-data/status", apiFetch);

  const connected = connection?.status === "connected" || connection?.status === "configured";
  const { data: catalog, mutate: mutateCatalog } = useSWR<PropertyCatalog>(
    connected ? "/integrations/google-data/properties" : null,
    apiFetch,
  );

  const gscProperty = gscOverride ?? connection?.gsc_property ?? "";
  const ga4Property = ga4Override ?? connection?.ga4_property_id ?? "";
  const selectedGa4Name = useMemo(
    () => catalog?.ga4_properties.find((item) => item.id === ga4Property)?.name || null,
    [catalog?.ga4_properties, ga4Property],
  );

  async function connectGoogle() {
    setBusy("connect");
    setMessage("");
    try {
      const result = await apiFetch<OAuthStart>("/integrations/google-data/start", {
        method: "POST",
      });
      window.location.assign(result.authorization_url);
    } catch (error) {
      setMessage(error instanceof OperatorApiError ? error.message : "Could not start Google authorization.");
      setBusy(null);
    }
  }

  async function saveProperties() {
    if (!gscProperty && !ga4Property) {
      setMessage("Choose at least one Search Console or GA4 property.");
      return;
    }
    setBusy("save");
    setMessage("");
    try {
      await apiFetch<GoogleConnection>("/integrations/google-data/properties", {
        method: "PUT",
        body: JSON.stringify({
          gsc_property: gscProperty || null,
          ga4_property_id: ga4Property || null,
          ga4_property_name: selectedGa4Name,
        }),
      });
      const synced = await apiFetch<GoogleConnection>("/integrations/google-data/sync", {
        method: "POST",
      });
      await Promise.all([mutateConnection(synced, false), mutateCatalog()]);
      setGscOverride(null);
      setGa4Override(null);
      if (synced.baseline_status === "failed") {
        setMessage(synced.last_error || "Google connected, but the first data check failed.");
        return;
      }
      setMessage(
        synced.baseline_status === "partial"
          ? "Google connected. One source verified; review the warning before launch."
          : "Search Console and Analytics access verified.",
      );
      onReady?.(synced);
    } catch (error) {
      setMessage(error instanceof OperatorApiError ? error.message : "Could not save or verify Google properties.");
    } finally {
      setBusy(null);
    }
  }

  if (isLoading) {
    return <div className="h-48 animate-pulse rounded-[20px] bg-[#f3f0e8]" />;
  }

  if (!connected) {
    return (
      <div className="rounded-[20px] border border-[rgba(32,32,32,0.1)] bg-[#f9f7f3] p-6 sm:p-8">
        <div className="grid h-12 w-12 place-items-center rounded-full bg-[#202020] font-semibold text-white">G</div>
        <h2 className="mt-5 text-2xl font-semibold tracking-[-0.035em]">Connect search and traffic truth</h2>
        <p className="mt-2 max-w-xl text-sm leading-6 text-[#646464]">
          Grant read-only access to Search Console and Google Analytics 4. Refresh tokens are encrypted and never returned to the browser.
        </p>
        {connection?.last_error && <p className="mt-4 text-sm text-red-700">{connection.last_error}</p>}
        {message && <p className="mt-4 text-sm text-red-700">{message}</p>}
        <button
          type="button"
          onClick={connectGoogle}
          disabled={busy === "connect"}
          className="mt-6 min-h-12 rounded-full bg-[#ea2804] px-6 text-sm font-semibold text-white hover:bg-[#c01f00] disabled:opacity-50"
        >
          {busy === "connect" ? "Opening Google…" : "Connect Google data"}
        </button>
      </div>
    );
  }

  const summary = connection?.baseline_summary || {};
  const clicks = metric(summary, "gsc", "clicks");
  const sessions = metric(summary, "ga4", "sessions");

  return (
    <div className="space-y-5">
      <div className="rounded-[20px] border border-emerald-200 bg-emerald-50 p-5 text-emerald-950">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-emerald-700">
              {connection?.status === "configured" ? "Google properties configured" : "Google connected"}
            </p>
            <p className="mt-1 break-all font-semibold">{connection?.google_email || "Authorized Google account"}</p>
          </div>
          <button type="button" onClick={connectGoogle} className="min-h-10 rounded-full border border-emerald-300 px-4 text-sm font-semibold">
            Reconnect
          </button>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <label className="block rounded-[18px] border border-[rgba(32,32,32,0.12)] bg-white p-5">
          <span className="text-xs font-semibold uppercase tracking-[0.14em] text-[#646464]">Search Console</span>
          <select
            value={gscProperty}
            onChange={(event) => setGscOverride(event.target.value)}
            className="mt-3 h-12 w-full rounded-full border border-[rgba(32,32,32,0.18)] bg-white px-4 text-sm"
          >
            <option value="">Choose a property</option>
            {catalog?.gsc_properties.map((property) => (
              <option key={property.id} value={property.id}>{property.name}</option>
            ))}
          </select>
          <span className="mt-2 block text-xs text-[#8d8d8d]">{catalog?.gsc_properties.length ?? 0} accessible properties</span>
        </label>

        <label className="block rounded-[18px] border border-[rgba(32,32,32,0.12)] bg-white p-5">
          <span className="text-xs font-semibold uppercase tracking-[0.14em] text-[#646464]">Google Analytics 4</span>
          <select
            value={ga4Property}
            onChange={(event) => setGa4Override(event.target.value)}
            className="mt-3 h-12 w-full rounded-full border border-[rgba(32,32,32,0.18)] bg-white px-4 text-sm"
          >
            <option value="">Choose a GA4 property</option>
            {catalog?.ga4_properties.map((property) => (
              <option key={property.id} value={property.id}>{property.name}</option>
            ))}
          </select>
          <span className="mt-2 block text-xs text-[#8d8d8d]">{catalog?.ga4_properties.length ?? 0} accessible properties</span>
        </label>
      </div>

      {connection?.last_synced_at && (
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="rounded-2xl bg-[#f3f0e8] p-4">
            <p className="text-xs uppercase tracking-[0.12em] text-[#646464]">Validation</p>
            <p className="mt-1 font-semibold capitalize">{connection.baseline_status}</p>
          </div>
          <div className="rounded-2xl bg-[#f3f0e8] p-4">
            <p className="text-xs uppercase tracking-[0.12em] text-[#646464]">GSC clicks · 28d</p>
            <p className="mt-1 font-semibold">{clicks ?? "—"}</p>
          </div>
          <div className="rounded-2xl bg-[#f3f0e8] p-4">
            <p className="text-xs uppercase tracking-[0.12em] text-[#646464]">GA4 sessions · 28d</p>
            <p className="mt-1 font-semibold">{sessions ?? "—"}</p>
          </div>
        </div>
      )}

      {message && <p className={`text-sm ${message.includes("verified") || message.includes("connected") ? "text-emerald-700" : "text-red-700"}`}>{message}</p>}
      {connection?.last_error && connection.baseline_status !== "ready" && <p className="text-sm text-amber-800">{connection.last_error}</p>}
      <button
        type="button"
        onClick={saveProperties}
        disabled={busy === "save" || !catalog}
        className="min-h-12 rounded-full bg-[#202020] px-6 text-sm font-semibold text-white hover:bg-black disabled:opacity-50"
      >
        {busy === "save" ? "Saving and verifying…" : connection?.status === "configured" ? "Update and verify" : "Save and verify Google data"}
      </button>
    </div>
  );
}
