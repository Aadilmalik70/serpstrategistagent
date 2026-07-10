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

export default function WorkspaceSettingsPage() {
  const { data: session, update } = useSession();
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [inviteUrl, setInviteUrl] = useState("");
  const [busy, setBusy] = useState(false);

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

  function showRequestError(requestError: unknown) {
    setError(
      requestError instanceof OperatorApiError
        ? requestError.message
        : "The request could not be completed.",
    );
  }

  async function switchWorkspace(workspaceId: string) {
    setBusy(true);
    setError("");
    await update({ workspaceId });
    window.location.reload();
  }

  async function createWorkspace(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    const form = event.currentTarget;
    const data = new FormData(form);
    try {
      const workspace = await apiFetch<WorkspaceSummary>("/workspaces", {
        method: "POST",
        body: JSON.stringify({ name: String(data.get("name") || "") }),
      });
      await mutateWorkspaces();
      await update({ workspaceId: workspace.id });
      window.location.reload();
    } catch (requestError) {
      showRequestError(requestError);
      setBusy(false);
    }
  }

  async function inviteMember(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    setInviteUrl("");
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

  async function changeRole(memberId: string, role: Member["role"]) {
    setBusy(true);
    setError("");
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
    setError("");
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
    setError("");
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
    <div className="min-h-screen bg-gray-50">
      <header className="border-b border-gray-200 bg-white px-6 py-4">
        <div className="mx-auto flex max-w-6xl items-center justify-between">
          <div>
            <Link href="/" className="text-sm text-blue-600 hover:underline">← Dashboard</Link>
            <h1 className="mt-1 text-2xl font-bold">Workspace settings</h1>
            <p className="text-sm text-gray-500">
              {currentWorkspace?.name || session?.workspaceName || "Active workspace"} · {activeRole}
            </p>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl space-y-8 px-6 py-8">
        {error && <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}
        {notice && <div className="rounded-md border border-green-200 bg-green-50 p-3 text-sm text-green-700">{notice}</div>}

        <section className="grid gap-6 lg:grid-cols-2">
          <div className="rounded-lg border border-gray-200 bg-white p-6">
            <h2 className="text-lg font-semibold">Your workspaces</h2>
            <div className="mt-4 space-y-3">
              {workspaces?.map((workspace) => (
                <div key={workspace.id} className="flex items-center justify-between rounded-md border border-gray-200 p-3">
                  <div>
                    <p className="font-medium">{workspace.name}</p>
                    <p className="text-xs text-gray-500">{workspace.role} · {workspace.slug}</p>
                  </div>
                  <button
                    type="button"
                    disabled={busy || workspace.id === session?.workspaceId}
                    onClick={() => switchWorkspace(workspace.id)}
                    className="rounded-md border border-gray-300 px-3 py-1.5 text-sm disabled:opacity-50"
                  >
                    {workspace.id === session?.workspaceId ? "Active" : "Switch"}
                  </button>
                </div>
              ))}
            </div>
          </div>

          <form onSubmit={createWorkspace} className="rounded-lg border border-gray-200 bg-white p-6">
            <h2 className="text-lg font-semibold">Create another workspace</h2>
            <p className="mt-1 text-sm text-gray-500">Use separate workspaces for clients, brands, or agency teams.</p>
            <label htmlFor="workspace-name" className="mt-4 block text-sm font-medium">Workspace name</label>
            <input id="workspace-name" name="name" minLength={2} maxLength={255} required className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2" />
            <button disabled={busy} className="mt-4 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
              Create workspace
            </button>
          </form>
        </section>

        <section className="rounded-lg border border-gray-200 bg-white p-6">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold">Team members</h2>
              <p className="text-sm text-gray-500">Owners control roles. Admins can invite and remove members.</p>
            </div>
          </div>
          <div className="mt-4 overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead><tr className="text-left text-gray-500"><th className="py-2 pr-4">Person</th><th className="py-2 pr-4">Role</th><th className="py-2">Actions</th></tr></thead>
              <tbody className="divide-y divide-gray-100">
                {members?.map((member) => (
                  <tr key={member.id}>
                    <td className="py-3 pr-4"><p className="font-medium">{member.name || member.email}</p><p className="text-xs text-gray-500">{member.email}{member.user_id === session?.user?.id ? " · You" : ""}</p></td>
                    <td className="py-3 pr-4">
                      {canManageRoles ? (
                        <select value={member.role} disabled={busy} onChange={(event) => changeRole(member.id, event.target.value as Member["role"])} className="rounded-md border border-gray-300 px-2 py-1">
                          <option value="owner">Owner</option><option value="admin">Admin</option><option value="member">Member</option>
                        </select>
                      ) : <span className="capitalize">{member.role}</span>}
                    </td>
                    <td className="py-3">
                      {canManageTeam && !(activeRole === "admin" && member.role !== "member") && (
                        <button type="button" disabled={busy} onClick={() => removeMember(member.id)} className="text-red-600 hover:underline disabled:opacity-50">Remove</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {canManageTeam && (
          <section className="grid gap-6 lg:grid-cols-2">
            <form onSubmit={inviteMember} className="rounded-lg border border-gray-200 bg-white p-6">
              <h2 className="text-lg font-semibold">Invite a teammate</h2>
              <label htmlFor="invite-email" className="mt-4 block text-sm font-medium">Email address</label>
              <input id="invite-email" name="email" type="email" required className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2" />
              <label htmlFor="invite-role" className="mt-4 block text-sm font-medium">Role</label>
              <select id="invite-role" name="role" className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2">
                <option value="member">Member</option>
                {activeRole === "owner" && <option value="admin">Admin</option>}
              </select>
              <button disabled={busy} className="mt-4 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">Create invitation</button>
              {inviteUrl && (
                <div className="mt-4 rounded-md bg-gray-50 p-3">
                  <p className="break-all text-xs text-gray-700">{inviteUrl}</p>
                  <button type="button" onClick={() => navigator.clipboard.writeText(inviteUrl)} className="mt-2 text-sm font-medium text-blue-600 hover:underline">Copy invitation link</button>
                </div>
              )}
            </form>

            <div className="rounded-lg border border-gray-200 bg-white p-6">
              <h2 className="text-lg font-semibold">Pending invitations</h2>
              <div className="mt-4 space-y-3">
                {invitations?.length === 0 && <p className="text-sm text-gray-500">No pending invitations.</p>}
                {invitations?.map((invitation) => (
                  <div key={invitation.id} className="flex items-center justify-between rounded-md border border-gray-200 p-3">
                    <div><p className="font-medium">{invitation.email}</p><p className="text-xs text-gray-500">{invitation.role} · expires {new Date(invitation.expires_at).toLocaleDateString()}</p></div>
                    <button type="button" disabled={busy} onClick={() => revokeInvitation(invitation.id)} className="text-sm text-red-600 hover:underline disabled:opacity-50">Revoke</button>
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
