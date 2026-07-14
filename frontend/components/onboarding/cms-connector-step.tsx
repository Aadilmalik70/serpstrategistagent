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

type GitHubRepository = {
  site_id: string;
  repository: string | null;
  connected: boolean;
  visibility: string | null;
  default_branch: string | null;
  execution_ready: boolean;
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

  const { data: integrations, mutate: mutateIntegrations } = useSWR<Integration[]>(
    siteId ? `/integrations?site_id=${siteId}` : null,
    apiFetch,
  );
  const { data: github, mutate: mutateGitHub } = useSWR<GitHubRepository>(
    siteId ? `/integrations/github-repository/${siteId}` : null,
    apiFetch,
  );
  const wordpress = useMemo(
    () => integrations?.find((item) => item.provider === "wordpress" && item.status !== "revoked") ?? null,
    [integrations],
  );

  function errorMessage(error: unknown) {
    return error instanceof OperatorApiError ? error.message : "The CMS connection could not be completed.";
  }

  async function connectGitHub(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy("github");
    setMessage("");
    const form = new FormData(event.currentTarget);
    try {
      const result = await apiFetch<GitHubRepository>("/integrations/github-repository", {
        method: "POST",
        body: JSON.stringify({
          site_id: siteId,
          repository: String(form.get("repository") || ""),
        }),
      });
      await mutateGitHub(result, false);
      setMessage("GitHub repository mapped. Write execution will use the governed GitHub App in the execution phase.");
      onReady("github", {
        connected: true,
        repository: result.repository,
        visibility: result.visibility,
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
          <span className="mt-2 block text-xl font-semibold">GitHub</span>
          <span className={`mt-2 block text-sm leading-6 ${mode === "github" ? "text-white/65" : "text-[#646464]"}`}>
            Map a public repository now. Private repository access and PR execution use the governed GitHub App later.
          </span>
          {github?.connected && <span className="mt-4 inline-flex rounded-full bg-[#2b9a66] px-3 py-1 text-xs font-semibold text-white">Mapped</span>}
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
        <form onSubmit={connectGitHub} className="rounded-[20px] border border-[rgba(32,32,32,0.12)] bg-[#f9f7f3] p-5 sm:p-6">
          <label className="block">
            <span className="text-sm font-semibold">Repository</span>
            <input
              name="repository"
              required
              defaultValue={github?.repository || ""}
              placeholder="owner/repository"
              autoComplete="off"
              className="mt-2 h-12 w-full rounded-full border border-[rgba(32,32,32,0.18)] bg-white px-5"
            />
          </label>
          <p className="mt-2 text-xs leading-5 text-[#646464]">Only public repositories can be verified in this onboarding slice. No GitHub token is requested or stored.</p>
          <button disabled={busy === "github"} className="mt-5 min-h-12 rounded-full bg-[#ea2804] px-6 text-sm font-semibold text-white disabled:opacity-50">
            {busy === "github" ? "Verifying repository…" : github?.connected ? "Update repository" : "Map repository"}
          </button>
        </form>
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

      {message && <p className={`text-sm leading-6 ${message.includes("connected") || message.includes("mapped") ? "text-emerald-700" : "text-red-700"}`}>{message}</p>}
    </div>
  );
}
