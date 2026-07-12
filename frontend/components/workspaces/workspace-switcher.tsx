"use client";

import Link from "next/link";
import { useSession } from "next-auth/react";
import { useState } from "react";
import useSWR from "swr";

import { apiFetch } from "@/lib/api";

type WorkspaceSummary = {
  id: string;
  name: string;
  slug: string;
  role: string;
  status: string;
};

export default function WorkspaceSwitcher() {
  const { data: session, update } = useSession();
  const [switching, setSwitching] = useState(false);
  const { data: workspaces } = useSWR<WorkspaceSummary[]>(
    session?.accessToken && session.workspaceId ? "/workspaces" : null,
    apiFetch,
  );

  async function handleSwitch(workspaceId: string) {
    if (!workspaceId || workspaceId === session?.workspaceId) return;
    setSwitching(true);
    await update({ workspaceId });
    window.location.assign("/");
  }

  if (!session?.workspaceId) return null;

  return (
    <div className="flex min-w-0 items-center gap-2">
      <div className="relative min-w-0">
        <label htmlFor="workspace-switcher" className="sr-only">
          Active workspace
        </label>
        <span className="pointer-events-none absolute left-3 top-1/2 h-2 w-2 -translate-y-1/2 rounded-full bg-[#2b9a66]" />
        <select
          id="workspace-switcher"
          value={session.workspaceId}
          onChange={(event) => handleSwitch(event.target.value)}
          disabled={switching || !workspaces}
          className="h-10 max-w-[12rem] appearance-none truncate rounded-full border border-[rgba(32,32,32,0.16)] bg-white py-2 pl-7 pr-9 text-sm font-semibold text-[#202020] disabled:opacity-60 sm:max-w-60"
        >
          {!workspaces && (
            <option value={session.workspaceId}>{session.workspaceName || "Loading workspace..."}</option>
          )}
          {workspaces?.map((workspace) => (
            <option key={workspace.id} value={workspace.id}>
              {workspace.name} · {workspace.role}
            </option>
          ))}
        </select>
        <svg
          viewBox="0 0 20 20"
          fill="currentColor"
          aria-hidden="true"
          className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#646464]"
        >
          <path fillRule="evenodd" d="M5.22 7.22a.75.75 0 0 1 1.06 0L10 10.94l3.72-3.72a.75.75 0 1 1 1.06 1.06l-4.25 4.25a.75.75 0 0 1-1.06 0L5.22 8.28a.75.75 0 0 1 0-1.06Z" clipRule="evenodd" />
        </svg>
      </div>
      <Link
        href="/settings"
        aria-label="Open settings"
        className="grid h-10 w-10 shrink-0 place-items-center rounded-full border border-[rgba(32,32,32,0.16)] bg-white text-[#202020] transition hover:border-[#202020] hover:bg-[#202020] hover:text-white"
      >
        <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <path d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z" />
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1.08-1.5 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6h.08A1.65 1.65 0 0 0 10 3.09V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9v.08A1.65 1.65 0 0 0 20.91 10H21a2 2 0 1 1 0 4h-.09A1.65 1.65 0 0 0 19.4 15Z" />
        </svg>
      </Link>
    </div>
  );
}
