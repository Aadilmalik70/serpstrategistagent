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
    <div className="flex items-center gap-2">
      <label htmlFor="workspace-switcher" className="sr-only">
        Active workspace
      </label>
      <select
        id="workspace-switcher"
        value={session.workspaceId}
        onChange={(event) => handleSwitch(event.target.value)}
        disabled={switching || !workspaces}
        className="max-w-56 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm disabled:opacity-60"
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
      <Link
        href="/settings/workspace"
        className="text-sm font-medium text-blue-600 hover:text-blue-700"
      >
        Manage
      </Link>
    </div>
  );
}
