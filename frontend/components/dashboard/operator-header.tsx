"use client";

import Link from "next/link";
import { signOut, useSession } from "next-auth/react";
import useSWR from "swr";

import WorkspaceSwitcher from "@/components/workspaces/workspace-switcher";
import { apiFetch } from "@/lib/api";

type ActionQueueSummary = {
  counts_by_status: Record<string, number>;
};

export default function OperatorHeader() {
  const { data: session } = useSession();
  const canUseApi = Boolean(session?.accessToken && session.workspaceId);
  const { data: actionQueue } = useSWR<ActionQueueSummary>(
    canUseApi ? "/operator-actions?limit=1" : null,
    apiFetch,
  );
  const approvals = actionQueue?.counts_by_status.needs_approval ?? 0;

  async function handleSignOut() {
    await signOut({ redirect: false });
    window.location.assign("/login");
  }

  return (
    <header className="operator-header">
      <div className="operator-header-inner">
        <Link href="/" className="operator-brand">
          <span className="operator-brand-mark">S</span>
          <span>
            <span className="operator-brand-name">SERP Strategists</span>
            <span className="operator-brand-subtitle">Growth operator console</span>
          </span>
        </Link>

        <div className="operator-header-actions">
          <Link href="/actions" className="operator-queue-link">
            Action queue{approvals > 0 ? ` · ${approvals}` : ""}
          </Link>
          <WorkspaceSwitcher />
          <button type="button" onClick={handleSignOut} className="operator-signout">
            Sign out
          </button>
        </div>
      </div>
    </header>
  );
}
