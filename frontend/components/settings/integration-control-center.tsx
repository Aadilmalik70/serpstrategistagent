"use client";

import Link from "next/link";
import { useSession } from "next-auth/react";
import { useSearchParams } from "next/navigation";
import { FormEvent, useMemo, useState } from "react";
import useSWR from "swr";

import { apiFetch, OperatorApiError } from "@/lib/api";

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

type GitHubRepositoryStatus = {
  site_id: string;
  repository: string | null;
  connected: boolean;
  visibility: string | null;
  default_branch?: string | null;
  installation_id: string | null;
  repository_id: number | null;
  authorization_source: "public" | "github_app";
  authorization_ready: boolean;
  execution_ready: boolean;
  patch_planning_ready: boolean;
};

type OAuthStart = { authorization_url: string };
type GitHubAppStart = { installation_url: string };
type GitHubAppInstallation = {
  id: string;
  installation_id: number;
  account_login: string;
  account_type: string;
  repository_selection: string;
  permissions: Record<string, string>;
  status: string;
  last_verified_at: string;
  created_at: string;
};
type GitHubAppStatus = {
  configured: boolean;
  connected: boolean;
  execution_enabled: boolean;
  patch_planning_enabled: boolean;
  installations: GitHubAppInstallation[];
};
type GitHubAuthorizedRepository = {
  installation_id: string;
  repository_id: number;
  full_name: string;
  private: boolean;
  visibility: string;
  default_branch: string | null;
  permissions: Record<string, boolean>;
};
type GitHubAuthorizedRepositoryList = {
  items: GitHubAuthorizedRepository[];
  total: number;
};

type TestResult = {
  id: string;
  provider: string;
  status: string;
  message: string;
  tested_at: string;
};

type ProviderCardProps = {
  initials: string;
  name: string;
  description: string;
  status: string;
  configured: boolean;
  detail: string;
  action: React.ReactNode;
};

function ProviderCard({ initials, name, description, status, configured, detail, action }: ProviderCardProps) {
  return (
    <article className="flex min-h-64 flex-col rounded-[18px] border border-[rgba(32,32,32,0.12)] bg-white p-5 sm:p-6">
      <div className="flex items-start justify-between gap-3">
        <div className="grid h-11 w-11 place-items-center rounded-2xl bg-[#202020] text-sm font-bold text-white">
          {initials}
        </div>
        <span
          className={`rounded-full px-3 py-1 text-[11px] font-semibold ${
            configured ? "bg-emerald-100 text-emerald-800" : "bg-[#f3f0e8] text-[#646464]"
          }`}
        >
          {status}
        </span>
      </div>
      <h3 className="mt-5 text-xl font-semibold tracking-[-0.03em]">{name}</h3>
      <p className="mt-2 flex-1 text-sm leading-6 text-[#646464]">{description}</p>
      <div className="mt-5 border-t border-[rgba(32,32,32,0.1)] pt-4">
        <p className="min-h-5 break-words text-xs font-semibold text-[#646464]">{detail}</p>
        <div className="mt-4">{action}</div>
      </div>
    </article>
  );
}

function statusBadge(status: string) {
  if (["connected", "configured", "active"].includes(status)) return "bg-[#2b9a66] text-white";
  if (status === "failed" || status === "error") return "bg-red-100 text-red-800";
  if (status === "limited") return "bg-amber-100 text-amber-900";
  return "bg-[#f3f0e8] text-[#575757]";
}

function metadataText(value: unknown) {
  return typeof value === "string" ? value : null;
}

function githubCallbackError(code: string | null) {
  if (!code) return "";
  const messages: Record<string, string> = {
    invalid_callback: "GitHub returned an incomplete installation callback. Start the installation again.",
    github_install_state_invalid: "The GitHub installation session expired or was already used. Start again.",
    github_installation_in_use: "That GitHub App installation is already connected to another workspace.",
    github_app_authorization_failed: "GitHub rejected the App authorization. Check the App configuration and permissions.",
    github_provider_unavailable: "GitHub is temporarily unavailable. Try the installation again shortly.",
  };
  return messages[code] || "The GitHub App installation could not be completed.";
}

export default function IntegrationControlCenter() {
  const { data: session } = useSession();
  const query = useSearchParams();
  const canManage = session?.workspaceRole === "owner" || session?.workspaceRole === "admin";
  const [showWordPressForm, setShowWordPressForm] = useState(false);
  const [showGitHubMapping, setShowGitHubMapping] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const { data: integrations, mutate: mutateIntegrations } = useSWR<Integration[]>(
    session?.accessToken && session.workspaceId ? "/integrations" : null,
    apiFetch,
  );
  const { data: sites } = useSWR<Site[]>(
    session?.accessToken && session.workspaceId ? "/sites" : null,
    apiFetch,
  );
  const { data: google, mutate: mutateGoogle } = useSWR<GoogleConnection>(
    session?.accessToken && session.workspaceId ? "/integrations/google-data/status" : null,
    apiFetch,
  );
  const { data: githubApp, mutate: mutateGitHubApp } = useSWR<GitHubAppStatus>(
    session?.accessToken && session.workspaceId ? "/integrations/github-app/status" : null,
    apiFetch,
  );
  const { data: authorizedRepositories, mutate: mutateAuthorizedRepositories } =
    useSWR<GitHubAuthorizedRepositoryList>(
      githubApp?.connected ? "/integrations/github-app/repositories" : null,
      apiFetch,
    );

  const githubKey = sites
    ? `github-repositories:${sites.map((site) => site.id).sort().join(",")}`
    : null;
  const { data: githubRepositories, mutate: mutateGithub } = useSWR<GitHubRepositoryStatus[]>(
    githubKey,
    async () =>
      Promise.all(
        (sites || []).map((site) =>
          apiFetch<GitHubRepositoryStatus>(`/integrations/github-repository/${site.id}`),
        ),
      ),
  );

  const siteNames = useMemo(
    () => new Map(sites?.map((site) => [site.id, site.name || site.domain]) ?? []),
    [sites],
  );
  const wordpress = integrations?.filter((integration) => integration.provider === "wordpress") ?? [];
  const connectedGithub = githubRepositories?.filter((repository) => repository.connected) ?? [];
  const googleAuthorized = google?.status === "connected" || google?.status === "configured";
  const gscConfigured = Boolean(googleAuthorized && google?.gsc_property);
  const ga4Configured = Boolean(googleAuthorized && google?.ga4_property_id);
  const activeInstallations = githubApp?.installations.filter((item) => item.status === "active") ?? [];
  const callbackError = githubCallbackError(query.get("github_app_error"));
  const callbackNotice = query.get("github_app") === "connected"
    ? "GitHub App authorization connected. Choose an authorized repository to map it to a site."
    : "";
  const activeCount =
    wordpress.length +
    connectedGithub.length +
    activeInstallations.length +
    Number(gscConfigured) +
    Number(ga4Configured);

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

  async function startGoogleOAuth() {
    setBusy("google");
    clearMessages();
    try {
      const response = await apiFetch<OAuthStart>("/integrations/google-data/start", { method: "POST" });
      window.location.assign(response.authorization_url);
    } catch (requestError) {
      showError(requestError);
      setBusy(null);
    }
  }

  async function startGitHubApp() {
    setBusy("github-app");
    clearMessages();
    try {
      const response = await apiFetch<GitHubAppStart>("/integrations/github-app/start", {
        method: "POST",
      });
      window.location.assign(response.installation_url);
    } catch (requestError) {
      showError(requestError);
      setBusy(null);
    }
  }

  async function mapAuthorizedRepository(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy("github-map");
    clearMessages();
    const form = event.currentTarget;
    const formData = new FormData(form);
    const selection = String(formData.get("repository") || "");
    const [installationId, repositoryId] = selection.split(":");
    try {
      await apiFetch<GitHubRepositoryStatus>("/integrations/github-repository", {
        method: "POST",
        body: JSON.stringify({
          site_id: String(formData.get("site_id") || ""),
          installation_id: installationId,
          repository_id: Number(repositoryId),
        }),
      });
      form.reset();
      setShowGitHubMapping(false);
      await Promise.all([mutateGithub(), mutateAuthorizedRepositories()]);
      setNotice("GitHub App repository authorization mapped to the selected site. Check the rollout badges before planning or execution.");
    } catch (requestError) {
      showError(requestError);
    } finally {
      setBusy(null);
    }
  }

  async function disconnectGitHubApp(installation: GitHubAppInstallation) {
    if (!window.confirm(`Disconnect the ${installation.account_login} GitHub App installation from this workspace?`)) return;
    setBusy(`github-app-${installation.id}`);
    clearMessages();
    try {
      await apiFetch(`/integrations/github-app/${installation.id}`, { method: "DELETE" });
      await Promise.all([mutateGitHubApp(), mutateGithub(), mutateAuthorizedRepositories()]);
      setNotice("GitHub App authorization was disconnected locally. No repository was modified.");
    } catch (requestError) {
      showError(requestError);
    } finally {
      setBusy(null);
    }
  }

  async function disconnectGoogle() {
    if (!window.confirm("Disconnect Search Console and GA4 from this workspace?")) return;
    setBusy("disconnect-google");
    clearMessages();
    try {
      await apiFetch("/integrations/google-data", { method: "DELETE" });
      await mutateGoogle();
      setNotice("Google Search Console and GA4 were disconnected.");
    } catch (requestError) {
      showError(requestError);
    } finally {
      setBusy(null);
    }
  }

  async function connectWordPress(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy("wordpress");
    clearMessages();
    const form = event.currentTarget;
    const formData = new FormData(form);

    try {
      const created = await apiFetch<Integration>("/integrations", {
        method: "POST",
        body: JSON.stringify({
          provider: "wordpress",
          label: String(formData.get("label") || "WordPress connection"),
          site_id: String(formData.get("site_id") || ""),
          external_account_id: "default",
          credentials: {
            url: String(formData.get("url") || ""),
            username: String(formData.get("username") || ""),
            application_password: String(formData.get("application_password") || ""),
          },
        }),
      });
      await apiFetch<TestResult>(`/integrations/${created.id}/test`, { method: "POST" });
      form.reset();
      setShowWordPressForm(false);
      await mutateIntegrations();
      setNotice("WordPress connected and verified.");
    } catch (requestError) {
      showError(requestError);
    } finally {
      setBusy(null);
    }
  }

  async function testWordPress(integration: Integration) {
    setBusy(`test-${integration.id}`);
    clearMessages();
    try {
      const result = await apiFetch<TestResult>(`/integrations/${integration.id}/test`, { method: "POST" });
      await mutateIntegrations();
      setNotice(`${integration.label}: ${result.message}`);
    } catch (requestError) {
      showError(requestError);
    } finally {
      setBusy(null);
    }
  }

  async function revokeWordPress(integration: Integration) {
    if (!window.confirm(`Revoke ${integration.label}? The stored secret will be permanently overwritten.`)) return;
    setBusy(`revoke-${integration.id}`);
    clearMessages();
    try {
      await apiFetch(`/integrations/${integration.id}`, { method: "DELETE" });
      await mutateIntegrations();
      setNotice(`${integration.label} was revoked.`);
    } catch (requestError) {
      showError(requestError);
    } finally {
      setBusy(null);
    }
  }

  async function disconnectGithub(repository: GitHubRepositoryStatus) {
    const label = repository.repository || "this GitHub repository";
    if (!window.confirm(`Disconnect ${label}?`)) return;
    setBusy(`github-${repository.site_id}`);
    clearMessages();
    try {
      await apiFetch(`/integrations/github-repository/${repository.site_id}`, { method: "DELETE" });
      await mutateGithub();
      setNotice(`${label} was disconnected.`);
    } catch (requestError) {
      showError(requestError);
    } finally {
      setBusy(null);
    }
  }

  const googleAction = googleAuthorized ? (
    <div className="flex flex-wrap gap-2">
      <Link
        href="/onboarding?step=google&edit=1"
        className="inline-flex min-h-10 items-center rounded-full bg-[#202020] px-4 text-sm font-semibold text-white hover:bg-black"
      >
        Manage properties
      </Link>
      {canManage && (
        <button
          type="button"
          onClick={disconnectGoogle}
          disabled={busy === "disconnect-google"}
          className="min-h-10 rounded-full border border-red-200 px-4 text-sm font-semibold text-red-700 hover:bg-red-50 disabled:opacity-50"
        >
          Disconnect
        </button>
      )}
    </div>
  ) : canManage ? (
    <button
      type="button"
      onClick={startGoogleOAuth}
      disabled={busy === "google"}
      className="min-h-10 rounded-full bg-[#ea2804] px-4 text-sm font-semibold text-white hover:bg-[#c01f00] disabled:opacity-50"
    >
      {busy === "google" ? "Opening Google…" : "Connect Google"}
    </button>
  ) : (
    <span className="text-xs text-[#8d8d8d]">Owner or admin required</span>
  );

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
              <span className="h-2 w-2 rounded-full bg-[#2b9a66]" /> Workspace connections
            </div>
            <h1 className="mt-5 text-[clamp(2.7rem,7vw,5rem)] font-semibold leading-[0.95] tracking-[-0.06em]">
              One source of truth for every connection.
            </h1>
            <p className="mt-5 max-w-2xl text-base leading-7 text-[#575757] sm:text-lg">
              This page reflects the connections created during onboarding, including selected Google properties and site-to-repository mappings.
            </p>
          </div>
        </div>
      </section>

      <main className="mx-auto max-w-7xl space-y-8 px-4 py-8 sm:px-6 sm:py-10 lg:px-8 lg:py-12">
        {(error || callbackError) && <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">{error || callbackError}</div>}
        {(notice || callbackNotice) && <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900">{notice || callbackNotice}</div>}

        <section>
          <div className="flex items-end justify-between gap-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#646464]">Provider catalog</p>
              <h2 className="mt-2 text-3xl font-semibold tracking-[-0.045em]">Available connections</h2>
            </div>
            <span className="text-sm text-[#646464]">{activeCount} active</span>
          </div>

          <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <ProviderCard
              initials="WP"
              name="WordPress"
              description="Encrypted application-password access for drafts, metadata and future governed execution."
              status={wordpress.length ? "Configured" : "Not connected"}
              configured={wordpress.length > 0}
              detail={wordpress.length ? `${wordpress.length} site connection${wordpress.length === 1 ? "" : "s"}` : "No WordPress site connected"}
              action={
                canManage ? (
                  <button
                    type="button"
                    onClick={() => setShowWordPressForm((value) => !value)}
                    className="min-h-10 rounded-full bg-[#ea2804] px-4 text-sm font-semibold text-white hover:bg-[#c01f00]"
                  >
                    {showWordPressForm ? "Close form" : "Connect WordPress"}
                  </button>
                ) : (
                  <span className="text-xs text-[#8d8d8d]">Owner or admin required</span>
                )
              }
            />

            <ProviderCard
              initials="GH"
              name="GitHub"
              description="GitHub App authorization for private repositories. Installation tokens stay server-side and expire after one hour."
              status={githubApp?.connected ? "Authorized" : githubApp?.configured ? "Not installed" : "Unavailable"}
              configured={Boolean(githubApp?.connected)}
              detail={
                activeInstallations.length
                  ? `${activeInstallations.length} App installation${activeInstallations.length === 1 ? "" : "s"} · ${githubApp?.patch_planning_enabled ? "AI patch planning enabled" : "patch planning disabled"}`
                  : githubApp?.configured
                    ? "Install the App to authorize repositories"
                    : "Configure the GitHub App on the backend"
              }
              action={
                canManage && githubApp?.configured ? (
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={startGitHubApp}
                      disabled={busy === "github-app"}
                      className="min-h-10 rounded-full bg-[#202020] px-4 text-sm font-semibold text-white hover:bg-black disabled:opacity-50"
                    >
                      {busy === "github-app" ? "Opening GitHub…" : githubApp.connected ? "Add installation" : "Install GitHub App"}
                    </button>
                    {githubApp.connected && (
                      <button
                        type="button"
                        onClick={() => setShowGitHubMapping((value) => !value)}
                        className="min-h-10 rounded-full border border-[#202020] px-4 text-sm font-semibold"
                      >
                        {showGitHubMapping ? "Close mapping" : "Map repository"}
                      </button>
                    )}
                  </div>
                ) : (
                  <span className="text-xs text-[#8d8d8d]">
                    {canManage ? "Backend configuration required" : "Owner or admin required"}
                  </span>
                )
              }
            />

            <ProviderCard
              initials="GS"
              name="Google Search Console"
              description="Read-only Search Analytics and property access for organic visibility measurement."
              status={gscConfigured ? "Configured" : googleAuthorized ? "Select property" : "Not connected"}
              configured={gscConfigured}
              detail={google?.gsc_property || google?.google_email || "No Search Console property selected"}
              action={googleAction}
            />

            <ProviderCard
              initials="GA"
              name="Google Analytics 4"
              description="Read-only GA4 property access for traffic, engagement and conversion measurement."
              status={ga4Configured ? "Configured" : googleAuthorized ? "Select property" : "Not connected"}
              configured={ga4Configured}
              detail={google?.ga4_property_name || google?.google_email || "No GA4 property selected"}
              action={googleAction}
            />
          </div>
        </section>

        {showWordPressForm && canManage && (
          <section className="overflow-hidden rounded-[22px] border border-[rgba(32,32,32,0.12)] bg-[#202020] text-white">
            <div className="border-b border-white/10 p-6 sm:p-8">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-white/55">New connection</p>
              <h2 className="mt-2 text-3xl font-semibold tracking-[-0.045em]">Connect WordPress</h2>
              <p className="mt-2 text-sm leading-6 text-white/65">The application password is encrypted, tested once and never returned to the browser.</p>
            </div>
            <form onSubmit={connectWordPress} className="grid gap-5 p-6 sm:grid-cols-2 sm:p-8">
              <label className="sm:col-span-2">
                <span className="text-sm font-semibold">Site</span>
                <select name="site_id" required className="mt-2 h-12 w-full rounded-full bg-white px-5 text-[#202020]">
                  <option value="">Choose a site</option>
                  {sites?.map((site) => <option key={site.id} value={site.id}>{site.name} · {site.domain}</option>)}
                </select>
              </label>
              <label className="sm:col-span-2">
                <span className="text-sm font-semibold">Connection label</span>
                <input name="label" defaultValue="Primary WordPress" required className="mt-2 h-12 w-full rounded-full bg-white px-5 text-[#202020]" />
              </label>
              <label>
                <span className="text-sm font-semibold">WordPress URL</span>
                <input name="url" type="url" required placeholder="https://example.com" className="mt-2 h-12 w-full rounded-full bg-white px-5 text-[#202020]" />
              </label>
              <label>
                <span className="text-sm font-semibold">Username</span>
                <input name="username" required className="mt-2 h-12 w-full rounded-full bg-white px-5 text-[#202020]" />
              </label>
              <label className="sm:col-span-2">
                <span className="text-sm font-semibold">Application password</span>
                <input name="application_password" type="password" autoComplete="off" required className="mt-2 h-12 w-full rounded-full bg-white px-5 text-[#202020]" />
              </label>
              <div className="sm:col-span-2 flex justify-end border-t border-white/10 pt-5">
                <button disabled={busy === "wordpress"} className="min-h-12 rounded-full bg-[#ea2804] px-6 text-sm font-semibold text-white disabled:opacity-50">
                  {busy === "wordpress" ? "Connecting and testing…" : "Save and test connection"}
                </button>
              </div>
            </form>
          </section>
        )}

        {showGitHubMapping && canManage && githubApp?.connected && (
          <section className="overflow-hidden rounded-[22px] border border-[rgba(32,32,32,0.12)] bg-[#202020] text-white">
            <div className="border-b border-white/10 p-6 sm:p-8">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-white/55">Authorized repository</p>
              <h2 className="mt-2 text-3xl font-semibold tracking-[-0.045em]">Map GitHub repository</h2>
              <p className="mt-2 text-sm leading-6 text-white/65">
                Mapping authorizes this site. When the rollout gate is enabled, only explicitly approved actions with exact file plans can create reviewable draft pull requests.
              </p>
            </div>
            <form onSubmit={mapAuthorizedRepository} className="grid gap-5 p-6 sm:grid-cols-2 sm:p-8">
              <label>
                <span className="text-sm font-semibold">Site</span>
                <select name="site_id" required className="mt-2 h-12 w-full rounded-full bg-white px-5 text-[#202020]">
                  <option value="">Choose a site</option>
                  {sites?.map((site) => <option key={site.id} value={site.id}>{site.name} · {site.domain}</option>)}
                </select>
              </label>
              <label>
                <span className="text-sm font-semibold">Authorized repository</span>
                <select name="repository" required className="mt-2 h-12 w-full rounded-full bg-white px-5 text-[#202020]">
                  <option value="">Choose a repository</option>
                  {authorizedRepositories?.items.map((repository) => (
                    <option
                      key={`${repository.installation_id}:${repository.repository_id}`}
                      value={`${repository.installation_id}:${repository.repository_id}`}
                    >
                      {repository.full_name} · {repository.visibility}
                    </option>
                  ))}
                </select>
              </label>
              <div className="sm:col-span-2 flex items-center justify-between gap-4 border-t border-white/10 pt-5">
                <p className="text-xs text-white/55">{authorizedRepositories?.total ?? 0} repositories authorized by GitHub</p>
                <button disabled={busy === "github-map"} className="min-h-12 rounded-full bg-[#ea2804] px-6 text-sm font-semibold text-white disabled:opacity-50">
                  {busy === "github-map" ? "Verifying authorization…" : "Map repository"}
                </button>
              </div>
            </form>
          </section>
        )}

        <section>
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#646464]">Connection inventory</p>
            <h2 className="mt-2 text-3xl font-semibold tracking-[-0.045em]">Configured integrations</h2>
          </div>

          <div className="mt-5 space-y-4">
            {activeCount === 0 && (
              <div className="rounded-[20px] border border-dashed border-[rgba(32,32,32,0.22)] bg-white px-5 py-12 text-center">
                <p className="font-semibold">No workspace connections configured</p>
                <p className="mt-2 text-sm text-[#646464]">Complete onboarding or connect a provider above.</p>
              </div>
            )}

            {gscConfigured && (
              <article className="rounded-[20px] border border-[rgba(32,32,32,0.12)] bg-white p-5 sm:p-6">
                <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="font-semibold">Google Search Console</h3>
                      <span className="rounded-full bg-[#2b9a66] px-2.5 py-1 text-[11px] font-semibold text-white">Configured</span>
                      <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${statusBadge(google?.baseline_status || "not_started")}`}>
                        {(google?.baseline_status || "not_started").replaceAll("_", " ")}
                      </span>
                    </div>
                    <p className="mt-1 break-all text-sm text-[#646464]">{google?.gsc_property}</p>
                    <p className="mt-2 text-xs text-[#8d8d8d]">Authorized as {google?.google_email || "Google account"}</p>
                  </div>
                  <Link href="/onboarding?step=google&edit=1" className="inline-flex min-h-10 items-center rounded-full bg-[#202020] px-4 text-sm font-semibold text-white">Manage</Link>
                </div>
              </article>
            )}

            {ga4Configured && (
              <article className="rounded-[20px] border border-[rgba(32,32,32,0.12)] bg-white p-5 sm:p-6">
                <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="font-semibold">Google Analytics 4</h3>
                      <span className="rounded-full bg-[#2b9a66] px-2.5 py-1 text-[11px] font-semibold text-white">Configured</span>
                    </div>
                    <p className="mt-1 text-sm text-[#646464]">{google?.ga4_property_name} · Property {google?.ga4_property_id}</p>
                    <p className="mt-2 text-xs text-[#8d8d8d]">Authorized as {google?.google_email || "Google account"}</p>
                  </div>
                  <Link href="/onboarding?step=google&edit=1" className="inline-flex min-h-10 items-center rounded-full bg-[#202020] px-4 text-sm font-semibold text-white">Manage</Link>
                </div>
              </article>
            )}

            {connectedGithub.map((repository) => (
              <article key={repository.site_id} className="rounded-[20px] border border-[rgba(32,32,32,0.12)] bg-white p-5 sm:p-6">
                <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="font-semibold">GitHub repository</h3>
                      <span className="rounded-full bg-[#2b9a66] px-2.5 py-1 text-[11px] font-semibold text-white">Configured</span>
                      <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${repository.authorization_ready ? "bg-blue-100 text-blue-900" : "bg-amber-100 text-amber-900"}`}>
                        {repository.authorization_ready ? "App authorized" : "Public mapping"}
                      </span>
                      <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${repository.execution_ready ? "bg-emerald-100 text-emerald-900" : "bg-[#f3f0e8] text-[#646464]"}`}>
                        {repository.execution_ready ? "Draft PR ready" : "Execution unavailable"}
                      </span>
                      <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${repository.patch_planning_ready ? "bg-blue-100 text-blue-900" : "bg-[#f3f0e8] text-[#646464]"}`}>
                        {repository.patch_planning_ready ? "Exact patch planning ready" : "Patch planning unavailable"}
                      </span>
                    </div>
                    <p className="mt-1 text-sm text-[#646464]">{repository.repository}</p>
                    <p className="mt-2 text-xs text-[#8d8d8d]">{siteNames.get(repository.site_id) || "Site"} · {repository.visibility || "unknown visibility"} · {repository.default_branch || "default branch unknown"}</p>
                  </div>
                  {canManage && (
                    <div className="flex flex-wrap gap-2">
                      <Link href="/onboarding?step=cms&edit=1" className="inline-flex min-h-10 items-center rounded-full bg-[#202020] px-4 text-sm font-semibold text-white">Manage</Link>
                      <button
                        type="button"
                        onClick={() => disconnectGithub(repository)}
                        disabled={busy === `github-${repository.site_id}`}
                        className="min-h-10 rounded-full border border-red-200 px-4 text-sm font-semibold text-red-700 hover:bg-red-50 disabled:opacity-50"
                      >
                        Disconnect
                      </button>
                    </div>
                  )}
                </div>
              </article>
            ))}

            {activeInstallations.map((installation) => (
              <article key={installation.id} className="rounded-[20px] border border-[rgba(32,32,32,0.12)] bg-white p-5 sm:p-6">
                <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="font-semibold">GitHub App · {installation.account_login}</h3>
                      <span className="rounded-full bg-[#2b9a66] px-2.5 py-1 text-[11px] font-semibold text-white">Authorized</span>
                      <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${githubApp?.execution_enabled ? "bg-emerald-100 text-emerald-900" : "bg-[#f3f0e8] text-[#646464]"}`}>
                        {githubApp?.execution_enabled ? "Governed draft PRs enabled" : "Execution rollout disabled"}
                      </span>
                      <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${githubApp?.patch_planning_enabled ? "bg-blue-100 text-blue-900" : "bg-[#f3f0e8] text-[#646464]"}`}>
                        {githubApp?.patch_planning_enabled ? "AI patch planner enabled" : "Patch planning disabled"}
                      </span>
                    </div>
                    <p className="mt-1 text-sm text-[#646464]">{installation.account_type} · {installation.repository_selection} repositories</p>
                    <p className="mt-2 text-xs text-[#8d8d8d]">Installation {installation.installation_id} · tokens are minted only when needed and never stored</p>
                  </div>
                  {canManage && (
                    <button
                      type="button"
                      onClick={() => disconnectGitHubApp(installation)}
                      disabled={busy === `github-app-${installation.id}`}
                      className="min-h-10 rounded-full border border-red-200 px-4 text-sm font-semibold text-red-700 hover:bg-red-50 disabled:opacity-50"
                    >
                      Disconnect authorization
                    </button>
                  )}
                </div>
              </article>
            ))}

            {wordpress.map((integration) => {
              const url = metadataText(integration.metadata.url);
              const secretHint = metadataText(integration.metadata.secret_hint);
              return (
                <article key={integration.id} className="rounded-[20px] border border-[rgba(32,32,32,0.12)] bg-white p-5 sm:p-6">
                  <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="font-semibold">{integration.label}</h3>
                        <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${statusBadge(integration.status)}`}>{integration.status}</span>
                        <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${statusBadge(integration.last_validation_status)}`}>{integration.last_validation_status.replaceAll("_", " ")}</span>
                      </div>
                      <p className="mt-1 text-sm text-[#646464]">WordPress · {siteNames.get(integration.site_id || "") || "Site"}</p>
                      <div className="mt-2 flex flex-wrap gap-3 font-mono text-xs text-[#8d8d8d]">
                        {url && <span>{url}</span>}
                        {secretHint && <span>{secretHint}</span>}
                      </div>
                    </div>
                    {canManage && (
                      <div className="flex flex-wrap gap-2">
                        <button type="button" onClick={() => testWordPress(integration)} disabled={busy === `test-${integration.id}`} className="min-h-10 rounded-full border border-[#202020] px-4 text-sm font-semibold hover:bg-[#202020] hover:text-white disabled:opacity-50">Test</button>
                        <button type="button" onClick={() => revokeWordPress(integration)} disabled={busy === `revoke-${integration.id}`} className="min-h-10 rounded-full border border-red-200 px-4 text-sm font-semibold text-red-700 hover:bg-red-50 disabled:opacity-50">Revoke</button>
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
