"use client";

import Link from "next/link";
import { useSession } from "next-auth/react";
import { FormEvent, useMemo, useState } from "react";
import useSWR from "swr";

import { apiFetch, OperatorApiError } from "@/lib/api";

type ProviderField = {
  name: string;
  label: string;
  secret: boolean;
  required: boolean;
  placeholder: string | null;
  help_text: string | null;
};

type ProviderDefinition = {
  id: string;
  name: string;
  description: string;
  connection_mode: string;
  scope: "workspace" | "site";
  available: boolean;
  test_supported: boolean;
  fields: ProviderField[];
};

type Integration = {
  id: string;
  provider: string;
  provider_name: string;
  label: string;
  site_id: string | null;
  scope: "workspace" | "site";
  external_account_id: string;
  status: string;
  metadata: Record<string, unknown>;
  last_validation_status: string;
  last_validation_error: string | null;
  last_validated_at: string | null;
  rotated_at: string | null;
  revoked_at: string | null;
  created_at: string;
  updated_at: string;
  test_supported: boolean;
};

type Site = {
  id: string;
  domain: string;
  name: string;
  status: string;
};

type TestResult = {
  id: string;
  provider: string;
  status: string;
  message: string;
  tested_at: string;
};

function statusBadge(status: string) {
  if (status === "connected" || status === "active") return "bg-[#2b9a66] text-white";
  if (status === "failed") return "bg-red-100 text-red-800";
  if (status === "limited") return "bg-amber-100 text-amber-900";
  if (status === "revoked") return "bg-[#202020] text-white";
  return "bg-[#f3f0e8] text-[#575757]";
}

function metadataText(value: unknown) {
  return typeof value === "string" ? value : null;
}

export default function IntegrationsPage() {
  const { data: session } = useSession();
  const canManage = session?.workspaceRole === "owner" || session?.workspaceRole === "admin";
  const [selectedProviderId, setSelectedProviderId] = useState<string | null>(null);
  const [editing, setEditing] = useState<Integration | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const { data: providers } = useSWR<ProviderDefinition[]>(
    session?.accessToken && session.workspaceId ? "/integrations/providers" : null,
    apiFetch,
  );
  const { data: integrations, mutate: mutateIntegrations } = useSWR<Integration[]>(
    session?.accessToken && session.workspaceId ? "/integrations" : null,
    apiFetch,
  );
  const { data: sites } = useSWR<Site[]>(
    session?.accessToken && session.workspaceId ? "/sites" : null,
    apiFetch,
  );

  const selectedProvider = useMemo(
    () => providers?.find((provider) => provider.id === selectedProviderId) ?? null,
    [providers, selectedProviderId],
  );
  const siteNames = useMemo(
    () => new Map(sites?.map((site) => [site.id, site.name || site.domain]) ?? []),
    [sites],
  );

  function clearMessages() {
    setError("");
    setNotice("");
  }

  function showError(requestError: unknown) {
    setError(
      requestError instanceof OperatorApiError
        ? requestError.message
        : "The integration request could not be completed.",
    );
  }

  function openConnect(provider: ProviderDefinition) {
    clearMessages();
    setEditing(null);
    setSelectedProviderId(provider.id);
    window.setTimeout(() => document.getElementById("integration-form")?.scrollIntoView({ behavior: "smooth" }), 10);
  }

  function openRotate(integration: Integration) {
    clearMessages();
    setEditing(integration);
    setSelectedProviderId(integration.provider);
    window.setTimeout(() => document.getElementById("integration-form")?.scrollIntoView({ behavior: "smooth" }), 10);
  }

  function closeForm() {
    setSelectedProviderId(null);
    setEditing(null);
  }

  async function submitIntegration(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedProvider) return;
    setBusy("save");
    clearMessages();

    const form = event.currentTarget;
    const formData = new FormData(form);
    const credentials: Record<string, string> = {};
    for (const field of selectedProvider.fields) {
      const value = String(formData.get(field.name) || "").trim();
      if (value) credentials[field.name] = value;
    }

    try {
      if (editing) {
        await apiFetch<Integration>(`/integrations/${editing.id}`, {
          method: "PUT",
          body: JSON.stringify({
            label: String(formData.get("label") || editing.label),
            credentials,
          }),
        });
        setNotice(`${selectedProvider.name} credentials rotated. Test the connection before use.`);
      } else {
        await apiFetch<Integration>("/integrations", {
          method: "POST",
          body: JSON.stringify({
            provider: selectedProvider.id,
            label: String(formData.get("label") || selectedProvider.name),
            site_id: selectedProvider.scope === "site" ? String(formData.get("site_id") || "") : null,
            external_account_id: "default",
            credentials,
          }),
        });
        setNotice(`${selectedProvider.name} connected securely. Test the connection before use.`);
      }
      form.reset();
      closeForm();
      await mutateIntegrations();
    } catch (requestError) {
      showError(requestError);
    } finally {
      setBusy(null);
    }
  }

  async function testConnection(integration: Integration) {
    setBusy(`test-${integration.id}`);
    clearMessages();
    try {
      const result = await apiFetch<TestResult>(`/integrations/${integration.id}/test`, {
        method: "POST",
      });
      setNotice(`${integration.provider_name}: ${result.message}`);
      await mutateIntegrations();
    } catch (requestError) {
      showError(requestError);
    } finally {
      setBusy(null);
    }
  }

  async function revokeConnection(integration: Integration) {
    if (!window.confirm(`Revoke ${integration.label}? The stored secret will be permanently overwritten.`)) return;
    setBusy(`revoke-${integration.id}`);
    clearMessages();
    try {
      await apiFetch(`/integrations/${integration.id}`, { method: "DELETE" });
      setNotice(`${integration.provider_name} access revoked and secret material destroyed.`);
      if (editing?.id === integration.id) closeForm();
      await mutateIntegrations();
    } catch (requestError) {
      showError(requestError);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="min-h-screen bg-[#f9f7f3] text-[#202020]">
      <header className="border-b border-[rgba(32,32,32,0.12)] bg-[#f9f7f3]">
        <div className="mx-auto flex min-h-[68px] max-w-7xl items-center justify-between gap-4 px-4 sm:px-6 lg:px-8">
          <Link href="/settings" className="inline-flex items-center gap-3 text-sm font-semibold">
            <span className="grid h-9 w-9 place-items-center rounded-full bg-[#202020] text-white">←</span>
            Settings
          </Link>
          <span className="rounded-full bg-[#f3f0e8] px-3 py-1.5 text-xs font-semibold capitalize text-[#575757]">
            {session?.workspaceRole}
          </span>
        </div>
      </header>

      <section className="operator-grid border-b border-[rgba(32,32,32,0.12)] bg-[#f3f0e8]">
        <div className="mx-auto max-w-7xl px-4 py-12 sm:px-6 sm:py-16 lg:px-8">
          <div className="max-w-3xl">
            <div className="inline-flex items-center gap-2 rounded-full border border-[rgba(32,32,32,0.12)] bg-white px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.14em] text-[#575757]">
              <span className="h-2 w-2 rounded-full bg-[#2b9a66]" /> Encrypted vault
            </div>
            <h1 className="mt-5 text-[clamp(2.7rem,7vw,5rem)] font-semibold leading-[0.95] tracking-[-0.06em]">
              Connect providers without leaking the keys.
            </h1>
            <p className="mt-5 max-w-2xl text-base leading-7 text-[#575757] sm:text-lg">
              Credentials are encrypted before storage, never returned by the API and permanently overwritten when revoked.
            </p>
          </div>
        </div>
      </section>

      <main className="mx-auto max-w-7xl space-y-8 px-4 py-8 sm:px-6 sm:py-10 lg:px-8 lg:py-12">
        {error && (
          <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm leading-6 text-red-800">{error}</div>
        )}
        {notice && (
          <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-4 text-sm leading-6 text-emerald-900">{notice}</div>
        )}

        <section>
          <div className="flex items-end justify-between gap-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#646464]">Provider catalog</p>
              <h2 className="mt-2 text-3xl font-semibold tracking-[-0.045em]">Available connections</h2>
            </div>
            <span className="text-sm text-[#646464]">{integrations?.length ?? 0} active</span>
          </div>

          <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {!providers && [1, 2, 3, 4, 5, 6].map((item) => (
              <div key={item} className="h-56 animate-pulse rounded-[18px] bg-[#f3f0e8]" />
            ))}
            {providers?.map((provider) => {
              const connectedCount = integrations?.filter((item) => item.provider === provider.id).length ?? 0;
              return (
                <article key={provider.id} className="flex min-h-56 flex-col rounded-[18px] border border-[rgba(32,32,32,0.12)] bg-white p-5 sm:p-6">
                  <div className="flex items-start justify-between gap-3">
                    <div className="grid h-11 w-11 place-items-center rounded-2xl bg-[#202020] text-sm font-bold text-white">
                      {provider.name.slice(0, 2).toUpperCase()}
                    </div>
                    <span className={`rounded-full px-3 py-1 text-[11px] font-semibold ${provider.available ? "bg-[#f3f0e8] text-[#575757]" : "bg-amber-100 text-amber-900"}`}>
                      {provider.available ? provider.scope : "OAuth foundation"}
                    </span>
                  </div>
                  <h3 className="mt-5 text-xl font-semibold tracking-[-0.03em]">{provider.name}</h3>
                  <p className="mt-2 flex-1 text-sm leading-6 text-[#646464]">{provider.description}</p>
                  <div className="mt-5 flex items-center justify-between gap-3 border-t border-[rgba(32,32,32,0.1)] pt-4">
                    <span className="text-xs font-semibold text-[#646464]">{connectedCount} connected</span>
                    {provider.available && canManage ? (
                      <button
                        type="button"
                        onClick={() => openConnect(provider)}
                        className="min-h-10 rounded-full bg-[#ea2804] px-4 text-sm font-semibold text-white hover:bg-[#c01f00]"
                      >
                        Connect
                      </button>
                    ) : (
                      <span className="text-xs text-[#8d8d8d]">
                        {provider.available ? "Owner or admin required" : "Measurement phase"}
                      </span>
                    )}
                  </div>
                </article>
              );
            })}
          </div>
        </section>

        {selectedProvider && canManage && (
          <section id="integration-form" className="overflow-hidden rounded-[22px] border border-[rgba(32,32,32,0.12)] bg-[#202020] text-white">
            <div className="border-b border-white/10 p-6 sm:p-8">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-white/55">
                    {editing ? "Rotate credential" : "New connection"}
                  </p>
                  <h2 className="mt-2 text-3xl font-semibold tracking-[-0.045em]">{selectedProvider.name}</h2>
                  <p className="mt-2 max-w-xl text-sm leading-6 text-white/65">
                    Secret values are write-only. Existing values cannot be displayed or recovered.
                  </p>
                </div>
                <button type="button" onClick={closeForm} className="grid h-10 w-10 place-items-center rounded-full border border-white/20 text-white">×</button>
              </div>
            </div>

            <form onSubmit={submitIntegration} className="grid gap-5 p-6 sm:grid-cols-2 sm:p-8">
              <div className="sm:col-span-2">
                <label htmlFor="integration-label" className="text-sm font-semibold">Connection label</label>
                <input
                  id="integration-label"
                  name="label"
                  required
                  minLength={2}
                  maxLength={255}
                  defaultValue={editing?.label || `${selectedProvider.name} connection`}
                  className="mt-2 h-12 w-full rounded-full border border-white/20 bg-white px-5 text-[#202020]"
                />
              </div>

              {selectedProvider.scope === "site" && !editing && (
                <div className="sm:col-span-2">
                  <label htmlFor="integration-site" className="text-sm font-semibold">Site</label>
                  <select id="integration-site" name="site_id" required className="mt-2 h-12 w-full rounded-full border border-white/20 bg-white px-5 text-[#202020]">
                    <option value="">Choose a site</option>
                    {sites?.map((site) => <option key={site.id} value={site.id}>{site.name} · {site.domain}</option>)}
                  </select>
                </div>
              )}

              {selectedProvider.fields.map((field) => (
                <div key={field.name} className={field.name === "application_password" || field.name === "api_key" ? "sm:col-span-2" : ""}>
                  <label htmlFor={`credential-${field.name}`} className="text-sm font-semibold">{field.label}</label>
                  <input
                    id={`credential-${field.name}`}
                    name={field.name}
                    type={field.secret ? "password" : field.name.includes("url") ? "url" : "text"}
                    required={field.required}
                    autoComplete="off"
                    placeholder={field.placeholder || undefined}
                    className="mt-2 h-12 w-full rounded-full border border-white/20 bg-white px-5 text-[#202020] placeholder:text-[#8d8d8d]"
                  />
                  {field.help_text && <p className="mt-1.5 text-xs leading-5 text-white/55">{field.help_text}</p>}
                </div>
              ))}

              <div className="flex flex-col gap-3 border-t border-white/10 pt-5 sm:col-span-2 sm:flex-row sm:items-center sm:justify-between">
                <p className="text-xs leading-5 text-white/55">Submitting replaces any typed secret in this browser form with an encrypted server-side value.</p>
                <button disabled={busy === "save"} className="min-h-12 rounded-full bg-[#ea2804] px-6 text-sm font-semibold text-white hover:bg-[#c01f00] disabled:opacity-50">
                  {busy === "save" ? "Saving securely…" : editing ? "Rotate credential" : "Save encrypted connection"}
                </button>
              </div>
            </form>
          </section>
        )}

        <section>
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#646464]">Credential inventory</p>
            <h2 className="mt-2 text-3xl font-semibold tracking-[-0.045em]">Connected integrations</h2>
          </div>

          <div className="mt-5 space-y-4">
            {!integrations && [1, 2].map((item) => <div key={item} className="h-40 animate-pulse rounded-[18px] bg-[#f3f0e8]" />)}
            {integrations?.length === 0 && (
              <div className="rounded-[20px] border border-dashed border-[rgba(32,32,32,0.22)] bg-white px-5 py-12 text-center">
                <p className="font-semibold">No provider credentials connected</p>
                <p className="mt-2 text-sm text-[#646464]">Choose a provider above. Secret values will never appear in this inventory.</p>
              </div>
            )}
            {integrations?.map((integration) => {
              const url = metadataText(integration.metadata.url) || metadataText(integration.metadata.base_url);
              const secretHint = metadataText(integration.metadata.secret_hint);
              return (
                <article key={integration.id} className="rounded-[20px] border border-[rgba(32,32,32,0.12)] bg-white p-5 sm:p-6">
                  <div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
                    <div className="flex min-w-0 items-start gap-4">
                      <div className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-[#202020] text-sm font-bold text-white">
                        {integration.provider_name.slice(0, 2).toUpperCase()}
                      </div>
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="font-semibold">{integration.label}</h3>
                          <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold capitalize ${statusBadge(integration.status)}`}>{integration.status}</span>
                          <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold capitalize ${statusBadge(integration.last_validation_status)}`}>{integration.last_validation_status.replaceAll("_", " ")}</span>
                        </div>
                        <p className="mt-1 text-sm text-[#646464]">
                          {integration.provider_name} · {integration.scope === "site" ? siteNames.get(integration.site_id || "") || "Site" : session?.workspaceName || "Workspace"}
                        </p>
                        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 font-mono text-xs text-[#8d8d8d]">
                          {secretHint && <span>{secretHint}</span>}
                          {url && <span className="max-w-72 truncate">{url}</span>}
                          {integration.last_validated_at && <span>Tested {new Date(integration.last_validated_at).toLocaleString()}</span>}
                        </div>
                        {integration.last_validation_error && <p className="mt-2 text-xs text-red-700">{integration.last_validation_error}</p>}
                      </div>
                    </div>

                    {canManage && (
                      <div className="flex flex-wrap gap-2 lg:justify-end">
                        {integration.test_supported && (
                          <button
                            type="button"
                            onClick={() => testConnection(integration)}
                            disabled={busy === `test-${integration.id}`}
                            className="min-h-10 rounded-full border border-[#202020] px-4 text-sm font-semibold hover:bg-[#202020] hover:text-white disabled:opacity-50"
                          >
                            {busy === `test-${integration.id}` ? "Testing…" : "Test"}
                          </button>
                        )}
                        <button type="button" onClick={() => openRotate(integration)} className="min-h-10 rounded-full bg-[#202020] px-4 text-sm font-semibold text-white hover:bg-black">Rotate</button>
                        <button
                          type="button"
                          onClick={() => revokeConnection(integration)}
                          disabled={busy === `revoke-${integration.id}`}
                          className="min-h-10 rounded-full border border-red-200 px-4 text-sm font-semibold text-red-700 hover:bg-red-50 disabled:opacity-50"
                        >
                          {busy === `revoke-${integration.id}` ? "Revoking…" : "Revoke"}
                        </button>
                      </div>
                    )}
                  </div>
                </article>
              );
            })}
          </div>
        </section>
      </main>
    </div>
  );
}
