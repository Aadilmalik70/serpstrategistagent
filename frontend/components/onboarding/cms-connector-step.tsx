"use client";

import { FormEvent, useMemo, useState } from "react";
import useSWR from "swr";

import { apiFetch, OperatorApiError } from "@/lib/api";

type Integration = {
  id: string;
  provider: string;
  label: string;
  site_id: string | null;
  status: string;
  last_validation_status: string;
  last_validation_error: string | null;
  metadata: Record<string, unknown>;
};

type GitHubStatus = {
  configured: boolean;
  installed: boolean;
  site_id: string;
  repository: string | null;
  installation_record_id: string | null;
  account_login: string | null;
  execution_ready: boolean;
};

type GitHubRepository = {
  installation_record_id: string;
  installation_id: number;
  account_login: string;
  full_name: string;
  private: boolean;
  default_branch: string | null;
};

type GitHubCatalog = {
  configured: boolean;
  repositories: GitHubRepository[];
};

type CmsMode = "github" | "wordpress";

export default function CmsConnectorStep({
  siteId,
  initialMode,
  onReady,
}: {
  siteId: string;
  initialMode?: string;
  onReady: (mode: CmsMode, details: Record<string, unknown>) => void;
}) {
  const [mode, setMode] = useState<CmsMode>(initialMode === "wordpress" ? "wordpress" : "github");
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [repository, setRepository] = useState("");

  const { data: integrations, mutate: mutateIntegrations } = useSWR<Integration[]>(
    siteId ? `/integrations?site_id=${siteId}` : null,
    apiFetch,
  );
  const { data: github, mutate: mutateGitHub } = useSWR<GitHubStatus>(
    siteId ? `/integrations/github-app/status/${siteId}` : null,
    apiFetch,
  );
  const { data: githubCatalog, mutate: mutateCatalog } = useSWR<GitHubCatalog>(
    github?.configured ? "/integrations/github-app/repositories" : null,
    apiFetch,
  );
  const wordpress = useMemo(
    () => integrations?.find((item) => item.provider === "wordpress" && item.status !== "revoked") ?? null,
    [integrations],
  );

  function errorMessage(error: unknown) {
    return error instanceof OperatorApiError ? error.message : "The CMS connection could not be completed.";
  }

  async function installGitHubApp() {
    setBusy("github-install");
    setMessage("");
    try {
      const result = await apiFetch<{ installation_url: string }>("/integrations/github-app/start", {
        method: "POST",
        body: JSON.stringify({ site_id: siteId }),
      });
      window.location.assign(result.installation_url);
    } catch (error) {
      setMessage(errorMessage(error));
      setBusy(null);
    }
  }

  async function chooseGitHubRepository() {
    const chosenName = repository || github?.repository || "";
    const selected = githubCatalog?.repositories.find((item) => item.full_name === chosenName);
    if (!selected) {
      setMessage("Choose a repository accessible to the installed GitHub App.");
      return;
    }
    setBusy("github-select");
    setMessage("");
    try {
      const result = await apiFetch<GitHubStatus>("/integrations/github-app/repository", {
        method: "PUT",
        body: JSON.stringify({
          site_id: siteId,
          installation_record_id: selected.installation_record_id,
          repository: selected.full_name,
        }),
      });
      await Promise.all([mutateGitHub(result, false), mutateCatalog()]);
      setMessage("GitHub App installed and repository connected.");
      onReady("github", {
        connected: true,
        repository: result.repository,
        installation_record_id: result.installation_record_id,
        execution_ready: result.execution_ready,
      });
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setBusy(null);
    }
  }

  async function connectWordPress(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy("wordpress");
    setMessage("");
    const form = new FormData(event.currentTarget);
    const credentials = {
      url: String(form.get("url") || ""),
      username: String(form.get("username") || ""),
      application_password: String(form.get("application_password") || ""),
    };
    try {
      const saved = wordpress
        ? await apiFetch<Integration>(`/integrations/${wordpress.id}`, {
            method: "PUT",
            body: JSON.stringify({ label: "Primary WordPress", credentials }),
          })
        : await apiFetch<Integration>("/integrations", {
            method: "POST",
            body: JSON.stringify({
              provider: "wordpress",
              label: "Primary WordPress",
              site_id: siteId,
              external_account_id: "default",
              credentials,
            }),
          });
      const tested = await apiFetch<{ status: string; message: string }>(
        `/integrations/${saved.id}/test`,
        { method: "POST" },
      );
      await mutateIntegrations();
      if (tested.status !== "connected") {
        setMessage(tested.message || "WordPress rejected the connection.");
        return;
      }
      setMessage("WordPress connected and verified.");
      onReady("wordpress", {
        connected: true,
        integration_id: saved.id,
        validation_status: tested.status,
      });
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-2">
        <button
          type="button"
          onClick={() => setMode("github")}
          className={`rounded-[20px] border p-5 text-left transition ${mode === "github" ? "border-[#202020] bg-[#202020] text-white" : "border-[rgba(32,32,32,0.12)] bg-white hover:bg-[#f9f7f3]"}`}
        >
          <span className="text-xs font-semibold uppercase tracking-[0.14em] opacity-60">Code</span>
          <span className="mt-2 block text-xl font-semibold">GitHub App</span>
          <span className={`mt-2 block text-sm leading-6 ${mode === "github" ? "text-white/65" : "text-[#646464]"}`}>
            Install the governed app, grant repository access, then select the codebase used for approved pull requests.
          </span>
          {github?.execution_ready && <span className="mt-4 inline-flex rounded-full bg-[#2b9a66] px-3 py-1 text-xs font-semibold text-white">Connected</span>}
        </button>

        <button
          type="button"
          onClick={() => setMode("wordpress")}
          className={`rounded-[20px] border p-5 text-left transition ${mode === "wordpress" ? "border-[#202020] bg-[#202020] text-white" : "border-[rgba(32,32,32,0.12)] bg-white hover:bg-[#f9f7f3]"}`}
        >
          <span className="text-xs font-semibold uppercase tracking-[0.14em] opacity-60">CMS</span>
          <span className="mt-2 block text-xl font-semibold">WordPress</span>
          <span className={`mt-2 block text-sm leading-6 ${mode === "wordpress" ? "text-white/65" : "text-[#646464]"}`}>
            Connect with an application password. Credentials are encrypted and tested before setup continues.
          </span>
          {wordpress && <span className="mt-4 inline-flex rounded-full bg-[#2b9a66] px-3 py-1 text-xs font-semibold text-white">Connected</span>}
        </button>
      </div>

      {mode === "github" ? (
        <div className="rounded-[20px] border border-[rgba(32,32,32,0.12)] bg-[#f9f7f3] p-5 sm:p-6">
          {!github?.configured ? (
            <div>
              <p className="font-semibold">GitHub App configuration required</p>
              <p className="mt-2 text-sm leading-6 text-[#646464]">The server is missing the GitHub App ID, slug, or private key. You can skip this step and reconnect later.</p>
            </div>
          ) : (
            <>
              <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="font-semibold">{github.installed ? `Installed for ${github.account_login}` : "Install SERP Strategists on GitHub"}</p>
                  <p className="mt-1 text-sm text-[#646464]">Installation tokens are short-lived and never stored in the browser or database.</p>
                </div>
                <button
                  type="button"
                  onClick={installGitHubApp}
                  disabled={busy === "github-install"}
                  className="min-h-11 rounded-full border border-[#202020] px-5 text-sm font-semibold disabled:opacity-50"
                >
                  {busy === "github-install" ? "Opening GitHub…" : github.installed ? "Manage installation" : "Install GitHub App"}
                </button>
              </div>

              {(githubCatalog?.repositories.length ?? 0) > 0 && (
                <div className="mt-5 border-t border-[rgba(32,32,32,0.1)] pt-5">
                  <label className="block">
                    <span className="text-sm font-semibold">Repository</span>
                    <select
                      value={repository || github.repository || ""}
                      onChange={(event) => setRepository(event.target.value)}
                      className="mt-2 h-12 w-full rounded-full border border-[rgba(32,32,32,0.18)] bg-white px-5"
                    >
                      <option value="">Choose a repository</option>
                      {githubCatalog?.repositories.map((item) => (
                        <option key={`${item.installation_id}-${item.full_name}`} value={item.full_name}>
                          {item.full_name}{item.private ? " · private" : " · public"}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button
                    type="button"
                    onClick={chooseGitHubRepository}
                    disabled={busy === "github-select" || !(repository || github.repository)}
                    className="mt-5 min-h-12 rounded-full bg-[#ea2804] px-6 text-sm font-semibold text-white disabled:opacity-50"
                  >
                    {busy === "github-select" ? "Connecting repository…" : github.execution_ready ? "Update repository" : "Connect repository"}
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      ) : (
        <form onSubmit={connectWordPress} className="grid gap-4 rounded-[20px] border border-[rgba(32,32,32,0.12)] bg-[#f9f7f3] p-5 sm:grid-cols-2 sm:p-6">
          <label className="block sm:col-span-2">
            <span className="text-sm font-semibold">WordPress URL</span>
            <input name="url" type="url" required placeholder="https://example.com" className="mt-2 h-12 w-full rounded-full border border-[rgba(32,32,32,0.18)] bg-white px-5" />
          </label>
          <label className="block">
            <span className="text-sm font-semibold">Username</span>
            <input name="username" required autoComplete="username" className="mt-2 h-12 w-full rounded-full border border-[rgba(32,32,32,0.18)] bg-white px-5" />
          </label>
          <label className="block">
            <span className="text-sm font-semibold">Application password</span>
            <input name="application_password" type="password" required autoComplete="new-password" className="mt-2 h-12 w-full rounded-full border border-[rgba(32,32,32,0.18)] bg-white px-5" />
          </label>
          <div className="sm:col-span-2">
            <button disabled={busy === "wordpress"} className="min-h-12 rounded-full bg-[#ea2804] px-6 text-sm font-semibold text-white disabled:opacity-50">
              {busy === "wordpress" ? "Saving and testing…" : wordpress ? "Rotate and retest" : "Connect WordPress"}
            </button>
          </div>
        </form>
      )}

      {message && <p className={`text-sm leading-6 ${message.includes("connected") ? "text-emerald-700" : "text-red-700"}`}>{message}</p>}
    </div>
  );
}
