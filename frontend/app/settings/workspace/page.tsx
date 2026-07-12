"use client";

import Link from "next/link";
import { useSession } from "next-auth/react";
import { FormEvent, useMemo, useState } from "react";
import useSWR from "swr";

import { apiFetch, OperatorApiError } from "@/lib/api";

type WorkspaceSummary = {
  id: string;
  name: string;
  slug: string;
  role: string;
  status: string;
};

type Member = {
  id: string;
  user_id: string;
  email: string;
  name: string | null;
  role: "owner" | "admin" | "member";
  status: string;
  joined_at: string;
};

type Invitation = {
  id: string;
  email: string;
  role: "admin" | "member";
  status: string;
  expires_at: string;
  created_at: string;
};

type CreatedInvitation = Invitation & { accept_token: string };

const CARD =
  "rounded-[18px] border border-[rgba(32,32,32,0.12)] bg-white text-[#202020]";
const FIELD =
  "h-12 w-full rounded-full border border-[rgba(32,32,32,0.18)] bg-white px-5 text-base text-[#202020] placeholder:text-[#8d8d8d] transition focus:border-[#202020] focus:outline-none";
const DARK_BUTTON =
  "inline-flex min-h-11 items-center justify-center rounded-full bg-[#202020] px-5 text-sm font-semibold text-[#fcfcfc] transition hover:bg-black disabled:cursor-not-allowed disabled:opacity-45";
const ORANGE_BUTTON =
  "inline-flex min-h-11 items-center justify-center rounded-full bg-[#ea2804] px-5 text-sm font-semibold text-white transition hover:bg-[#c01f00] disabled:cursor-not-allowed disabled:opacity-45";

function initials(name: string | null, email: string) {
  const source = (name || email.split("@", 1)[0]).trim();
  return source
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");
}

function roleDescription(role: Member["role"]) {
  if (role === "owner") return "Full control, billing and roles";
  if (role === "admin") return "Manage sites and invite members";
  return "View sites and operator activity";
}

function RoleBadge({ role }: { role: string }) {
  const className =
    role === "owner"
      ? "bg-[#202020] text-white"
      : role === "admin"
        ? "bg-[#f3f0e8] text-[#202020]"
        : "border border-[rgba(32,32,32,0.12)] bg-white text-[#575757]";

  return (
    <span className={`inline-flex rounded-full px-3 py-1 text-xs font-semibold capitalize ${className}`}>
      {role}
    </span>
  );
}

function StatCard({ label, value, note }: { label: string; value: string | number; note: string }) {
  return (
    <div className={`${CARD} p-5 sm:p-6`}>
      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#646464]">{label}</p>
      <p className="mt-3 text-3xl font-semibold tracking-[-0.04em] text-[#202020]">{value}</p>
      <p className="mt-1 text-sm text-[#646464]">{note}</p>
    </div>
  );
}

export default function WorkspaceSettingsPage() {
  const { data: session, update } = useSession();
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [inviteUrl, setInviteUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  const activeRole = session?.workspaceRole;
  const canManageTeam = activeRole === "owner" || activeRole === "admin";
  const canManageRoles = activeRole === "owner";

  const { data: workspaces, mutate: mutateWorkspaces } = useSWR<WorkspaceSummary[]>(
    session?.accessToken && session.workspaceId ? "/workspaces" : null,
    apiFetch,
  );
  const { data: members, mutate: mutateMembers } = useSWR<Member[]>(
    session?.accessToken && session.workspaceId ? "/workspaces/members" : null,
    apiFetch,
  );
  const { data: invitations, mutate: mutateInvitations } = useSWR<Invitation[]>(
    session?.accessToken && session.workspaceId && canManageTeam
      ? "/workspaces/invitations"
      : null,
    apiFetch,
  );

  const currentWorkspace = useMemo(
    () => workspaces?.find((workspace) => workspace.id === session?.workspaceId),
    [workspaces, session?.workspaceId],
  );
  const ownerCount = members?.filter((member) => member.role === "owner").length ?? 0;
  const activeName = currentWorkspace?.name || session?.workspaceName || "Active workspace";

  function clearMessages() {
    setError("");
    setNotice("");
  }

  function showRequestError(requestError: unknown) {
    setError(
      requestError instanceof OperatorApiError
        ? requestError.message
        : "The request could not be completed.",
    );
  }

  async function switchWorkspace(workspaceId: string) {
    if (workspaceId === session?.workspaceId) return;
    setBusy(true);
    clearMessages();
    try {
      await update({ workspaceId });
      window.location.assign("/settings/workspace");
    } catch {
      setError("Workspace switching failed. Please try again.");
      setBusy(false);
    }
  }

  async function createWorkspace(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    clearMessages();
    const form = event.currentTarget;
    const data = new FormData(form);
    try {
      const workspace = await apiFetch<WorkspaceSummary>("/workspaces", {
        method: "POST",
        body: JSON.stringify({ name: String(data.get("name") || "") }),
      });
      await mutateWorkspaces();
      await update({ workspaceId: workspace.id });
      window.location.assign("/settings/workspace");
    } catch (requestError) {
      showRequestError(requestError);
      setBusy(false);
    }
  }

  async function inviteMember(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    clearMessages();
    setInviteUrl("");
    setCopied(false);
    const form = event.currentTarget;
    const data = new FormData(form);
    try {
      const invitation = await apiFetch<CreatedInvitation>("/workspaces/invitations", {
        method: "POST",
        body: JSON.stringify({
          email: String(data.get("email") || ""),
          role: String(data.get("role") || "member"),
        }),
      });
      const url = `${window.location.origin}/invite/${invitation.accept_token}`;
      setInviteUrl(url);
      setNotice("Invitation created. Share the secure link with the invited person.");
      form.reset();
      await mutateInvitations();
    } catch (requestError) {
      showRequestError(requestError);
    } finally {
      setBusy(false);
    }
  }

  async function copyInvitation() {
    try {
      await navigator.clipboard.writeText(inviteUrl);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2200);
    } catch {
      setError("Copy failed. Select and copy the invitation link manually.");
    }
  }

  async function changeRole(memberId: string, role: Member["role"]) {
    setBusy(true);
    clearMessages();
    try {
      await apiFetch(`/workspaces/members/${memberId}`, {
        method: "PATCH",
        body: JSON.stringify({ role }),
      });
      await mutateMembers();
      setNotice("Member role updated.");
    } catch (requestError) {
      showRequestError(requestError);
    } finally {
      setBusy(false);
    }
  }

  async function removeMember(memberId: string) {
    if (!window.confirm("Remove this person from the workspace?")) return;
    setBusy(true);
    clearMessages();
    try {
      await apiFetch(`/workspaces/members/${memberId}`, { method: "DELETE" });
      await mutateMembers();
      setNotice("Member removed.");
    } catch (requestError) {
      showRequestError(requestError);
    } finally {
      setBusy(false);
    }
  }

  async function revokeInvitation(invitationId: string) {
    setBusy(true);
    clearMessages();
    try {
      await apiFetch(`/workspaces/invitations/${invitationId}`, { method: "DELETE" });
      await mutateInvitations();
      setNotice("Invitation revoked.");
    } catch (requestError) {
      showRequestError(requestError);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen bg-[#f9f7f3] text-[#202020]">
      <header className="border-b border-[rgba(32,32,32,0.12)] bg-[#f9f7f3]">
        <div className="mx-auto flex min-h-[68px] max-w-7xl items-center justify-between gap-4 px-4 sm:px-6 lg:px-8">
          <Link href="/" className="inline-flex items-center gap-3 text-sm font-semibold text-[#202020]">
            <span className="grid h-9 w-9 place-items-center rounded-full bg-[#202020] text-white" aria-hidden="true">
              <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="m15 18-6-6 6-6" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </span>
            <span className="hidden sm:inline">Back to operator</span>
            <span className="sm:hidden">Back</span>
          </Link>
          <div className="flex items-center gap-3">
            <span className="hidden text-sm text-[#646464] sm:inline">{session?.user?.email}</span>
            <RoleBadge role={activeRole || "member"} />
          </div>
        </div>
      </header>

      <section className="operator-grid border-b border-[rgba(32,32,32,0.12)] bg-[#f3f0e8]">
        <div className="mx-auto max-w-7xl px-4 py-10 sm:px-6 sm:py-14 lg:px-8 lg:py-16">
          <div className="max-w-3xl">
            <div className="inline-flex items-center gap-2 rounded-full border border-[rgba(32,32,32,0.12)] bg-white px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.14em] text-[#575757]">
              <span className="h-2 w-2 rounded-full bg-[#2b9a66]" />
              Workspace control
            </div>
            <h1 className="mt-5 max-w-3xl text-[clamp(2.4rem,7vw,4.7rem)] font-semibold leading-[0.98] tracking-[-0.055em] text-[#202020]">
              Keep every brand, client and teammate in the right lane.
            </h1>
            <p className="mt-5 max-w-2xl text-base leading-7 text-[#575757] sm:text-lg">
              Separate sites, data and permissions by workspace. Invite collaborators without exposing another client&apos;s operator history.
            </p>
          </div>
        </div>
      </section>

      <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6 sm:py-10 lg:px-8 lg:py-12">
        <div aria-live="polite" className="space-y-3">
          {error && (
            <div className="flex items-start gap-3 rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">
              <span className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full bg-red-100 font-bold">!</span>
              <p>{error}</p>
            </div>
          )}
          {notice && (
            <div className="flex items-start gap-3 rounded-2xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900">
              <span className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full bg-emerald-100">✓</span>
              <p>{notice}</p>
            </div>
          )}
        </div>

        <section className="mt-6 grid gap-4 sm:grid-cols-3">
          <StatCard label="Active workspace" value={activeName} note={`You are ${activeRole || "member"}`} />
          <StatCard label="Workspaces" value={workspaces?.length ?? "—"} note="Isolated operating environments" />
          <StatCard label="Team" value={members?.length ?? "—"} note={`${ownerCount} owner${ownerCount === 1 ? "" : "s"}`} />
        </section>

        <section className="mt-8 grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
          <div className={`${CARD} overflow-hidden`}>
            <div className="border-b border-[rgba(32,32,32,0.12)] p-5 sm:p-7">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#646464]">Environment</p>
              <div className="mt-2 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
                <div>
                  <h2 className="text-2xl font-semibold tracking-[-0.035em]">Your workspaces</h2>
                  <p className="mt-1 text-sm leading-6 text-[#646464]">Switch context without mixing sites, reports or team access.</p>
                </div>
                <span className="text-sm font-medium text-[#646464]">{workspaces?.length ?? 0} total</span>
              </div>
            </div>

            <div className="divide-y divide-[rgba(32,32,32,0.1)]">
              {!workspaces && (
                <div className="space-y-3 p-5 sm:p-7">
                  {[1, 2].map((item) => <div key={item} className="h-20 animate-pulse rounded-2xl bg-[#f3f0e8]" />)}
                </div>
              )}
              {workspaces?.map((workspace) => {
                const active = workspace.id === session?.workspaceId;
                return (
                  <div key={workspace.id} className={`flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between sm:p-6 ${active ? "bg-[#f3f0e8]" : "bg-white"}`}>
                    <div className="flex min-w-0 items-center gap-4">
                      <div className={`grid h-12 w-12 shrink-0 place-items-center rounded-2xl text-sm font-bold ${active ? "bg-[#ea2804] text-white" : "bg-[#202020] text-white"}`}>
                        {workspace.name.slice(0, 2).toUpperCase()}
                      </div>
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="truncate font-semibold text-[#202020]">{workspace.name}</h3>
                          {active && <span className="rounded-full bg-[#2b9a66] px-2.5 py-1 text-[11px] font-semibold text-white">Active</span>}
                        </div>
                        <p className="mt-1 truncate font-mono text-xs text-[#646464]">{workspace.slug}</p>
                      </div>
                    </div>
                    <div className="flex items-center justify-between gap-3 sm:justify-end">
                      <RoleBadge role={workspace.role} />
                      <button
                        type="button"
                        disabled={busy || active}
                        onClick={() => switchWorkspace(workspace.id)}
                        className="min-h-10 rounded-full border border-[#202020] px-4 text-sm font-semibold text-[#202020] transition hover:bg-[#202020] hover:text-white disabled:border-[rgba(32,32,32,0.12)] disabled:text-[#8d8d8d]"
                      >
                        {active ? "Current" : "Switch"}
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <form onSubmit={createWorkspace} className={`${CARD} p-5 sm:p-7`}>
            <span className="grid h-11 w-11 place-items-center rounded-full bg-[#ea2804] text-2xl text-white">+</span>
            <p className="mt-6 text-xs font-semibold uppercase tracking-[0.16em] text-[#646464]">New environment</p>
            <h2 className="mt-2 text-3xl font-semibold leading-tight tracking-[-0.045em]">Create another workspace</h2>
            <p className="mt-3 text-sm leading-6 text-[#646464]">Best for a new client, product line or agency delivery team.</p>
            <label htmlFor="workspace-name" className="mt-7 block text-sm font-semibold text-[#202020]">Workspace name</label>
            <input id="workspace-name" name="name" minLength={2} maxLength={255} required placeholder="Acme growth team" className={`${FIELD} mt-2`} />
            <button disabled={busy} className={`${DARK_BUTTON} mt-4 w-full sm:w-auto`}>
              {busy ? "Working…" : "Create workspace"}
            </button>
          </form>
        </section>

        <section className={`${CARD} mt-6 overflow-hidden`}>
          <div className="border-b border-[rgba(32,32,32,0.12)] p-5 sm:p-7">
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#646464]">Access</p>
            <div className="mt-2 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
              <div>
                <h2 className="text-2xl font-semibold tracking-[-0.035em]">Team members</h2>
                <p className="mt-1 text-sm leading-6 text-[#646464]">Owners control roles. Admins can operate sites and invite members.</p>
              </div>
              <div className="flex flex-wrap gap-2 text-xs text-[#646464]">
                <span className="rounded-full bg-[#f3f0e8] px-3 py-1.5">Owner · full control</span>
                <span className="rounded-full bg-[#f3f0e8] px-3 py-1.5">Admin · operate</span>
                <span className="rounded-full bg-[#f3f0e8] px-3 py-1.5">Member · observe</span>
              </div>
            </div>
          </div>

          <div className="divide-y divide-[rgba(32,32,32,0.1)]">
            {!members && (
              <div className="p-5 sm:p-7"><div className="h-24 animate-pulse rounded-2xl bg-[#f3f0e8]" /></div>
            )}
            {members?.map((member) => {
              const isSelf = member.user_id === session?.user?.id;
              const isFinalOwner = member.role === "owner" && ownerCount <= 1;
              const adminCanRemove = activeRole === "admin" && member.role === "member";
              const ownerCanRemove = activeRole === "owner";
              const canRemove = !isSelf && !isFinalOwner && (adminCanRemove || ownerCanRemove);
              const canChangeThisRole = canManageRoles && !(isSelf && isFinalOwner);

              return (
                <article key={member.id} className="grid gap-4 p-5 sm:grid-cols-[minmax(0,1fr)_minmax(180px,0.45fr)_auto] sm:items-center sm:p-6">
                  <div className="flex min-w-0 items-center gap-4">
                    <div className="grid h-12 w-12 shrink-0 place-items-center rounded-full bg-[#202020] text-sm font-bold text-white">
                      {initials(member.name, member.email)}
                    </div>
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="truncate font-semibold text-[#202020]">{member.name || member.email}</h3>
                        {isSelf && <span className="rounded-full bg-[#f3f0e8] px-2.5 py-1 text-[11px] font-semibold text-[#575757]">You</span>}
                      </div>
                      <p className="mt-1 truncate text-sm text-[#646464]">{member.email}</p>
                    </div>
                  </div>

                  <div>
                    {canChangeThisRole ? (
                      <select
                        value={member.role}
                        disabled={busy}
                        onChange={(event) => changeRole(member.id, event.target.value as Member["role"])}
                        className="h-11 w-full rounded-full border border-[rgba(32,32,32,0.18)] bg-white px-4 text-sm font-semibold text-[#202020]"
                      >
                        <option value="owner">Owner</option>
                        <option value="admin">Admin</option>
                        <option value="member">Member</option>
                      </select>
                    ) : (
                      <div>
                        <RoleBadge role={member.role} />
                        <p className="mt-1.5 text-xs text-[#646464]">{roleDescription(member.role)}</p>
                      </div>
                    )}
                  </div>

                  <div className="flex justify-end">
                    {canRemove ? (
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => removeMember(member.id)}
                        className="min-h-10 rounded-full border border-red-200 px-4 text-sm font-semibold text-red-700 transition hover:bg-red-50 disabled:opacity-45"
                      >
                        Remove
                      </button>
                    ) : (
                      <span className="text-xs text-[#8d8d8d]">{isFinalOwner ? "Required owner" : isSelf ? "Signed-in account" : "Protected role"}</span>
                    )}
                  </div>
                </article>
              );
            })}
          </div>
        </section>

        {canManageTeam && (
          <section className="mt-6 grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
            <form onSubmit={inviteMember} className="rounded-[18px] bg-[#202020] p-5 text-white sm:p-7">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-white/60">Invite access</p>
              <h2 className="mt-2 text-3xl font-semibold tracking-[-0.045em] text-white">Bring in a teammate</h2>
              <p className="mt-3 text-sm leading-6 text-white/70">The secure invitation link expires in seven days and only works for the invited email.</p>

              <label htmlFor="invite-email" className="mt-7 block text-sm font-semibold text-white">Email address</label>
              <input id="invite-email" name="email" type="email" required placeholder="teammate@company.com" className="mt-2 h-12 w-full rounded-full border border-white/20 bg-white px-5 text-[#202020] placeholder:text-[#8d8d8d]" />

              <label htmlFor="invite-role" className="mt-4 block text-sm font-semibold text-white">Role</label>
              <select id="invite-role" name="role" className="mt-2 h-12 w-full rounded-full border border-white/20 bg-white px-5 text-[#202020]">
                <option value="member">Member — view and collaborate</option>
                {activeRole === "owner" && <option value="admin">Admin — manage sites and invites</option>}
              </select>

              <button disabled={busy} className={`${ORANGE_BUTTON} mt-5 w-full sm:w-auto`}>
                {busy ? "Creating…" : "Create invitation"}
              </button>

              {inviteUrl && (
                <div className="mt-5 rounded-2xl border border-white/15 bg-black p-4">
                  <p className="text-xs font-semibold uppercase tracking-[0.14em] text-white/55">Secure invitation link</p>
                  <p className="mt-2 break-all font-mono text-xs leading-5 text-white/80">{inviteUrl}</p>
                  <button type="button" onClick={copyInvitation} className="mt-3 rounded-full bg-white px-4 py-2 text-sm font-semibold text-[#202020]">
                    {copied ? "Copied" : "Copy link"}
                  </button>
                </div>
              )}
            </form>

            <div className={`${CARD} overflow-hidden`}>
              <div className="border-b border-[rgba(32,32,32,0.12)] p-5 sm:p-7">
                <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#646464]">Open requests</p>
                <div className="mt-2 flex items-end justify-between gap-3">
                  <div>
                    <h2 className="text-2xl font-semibold tracking-[-0.035em]">Pending invitations</h2>
                    <p className="mt-1 text-sm text-[#646464]">Revoke any link that should no longer grant access.</p>
                  </div>
                  <span className="rounded-full bg-[#f3f0e8] px-3 py-1.5 text-xs font-semibold text-[#575757]">{invitations?.length ?? 0} pending</span>
                </div>
              </div>
              <div className="divide-y divide-[rgba(32,32,32,0.1)]">
                {!invitations && <div className="p-5 sm:p-7"><div className="h-20 animate-pulse rounded-2xl bg-[#f3f0e8]" /></div>}
                {invitations?.length === 0 && (
                  <div className="p-8 text-center">
                    <div className="mx-auto grid h-12 w-12 place-items-center rounded-full bg-[#f3f0e8] text-xl">✓</div>
                    <p className="mt-3 font-semibold">No invitations waiting</p>
                    <p className="mt-1 text-sm text-[#646464]">New invitations will appear here.</p>
                  </div>
                )}
                {invitations?.map((invitation) => (
                  <div key={invitation.id} className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between sm:p-6">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="truncate font-semibold text-[#202020]">{invitation.email}</p>
                        <RoleBadge role={invitation.role} />
                      </div>
                      <p className="mt-1 text-xs text-[#646464]">Expires {new Date(invitation.expires_at).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}</p>
                    </div>
                    <button type="button" disabled={busy} onClick={() => revokeInvitation(invitation.id)} className="min-h-10 rounded-full border border-red-200 px-4 text-sm font-semibold text-red-700 hover:bg-red-50 disabled:opacity-45">
                      Revoke
                    </button>
                  </div>
                ))}
              </div>
            </div>
          </section>
        )}
      </main>
    </div>
  );
}
