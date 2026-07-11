"use client";

import Link from "next/link";
import { use, useState } from "react";
import { signOut, useSession } from "next-auth/react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type WorkspaceSummary = {
  id: string;
  name: string;
  slug: string;
  role: string;
  status: string;
};

export default function InvitationPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = use(params);
  const { data: session, status, update } = useSession();
  const [error, setError] = useState("");
  const [accepting, setAccepting] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [accountMismatch, setAccountMismatch] = useState(false);

  const callbackUrl = `/invite/${encodeURIComponent(token)}`;
  const loginUrl = `/login?callbackUrl=${encodeURIComponent(callbackUrl)}`;
  const registerUrl = `/register?callbackUrl=${encodeURIComponent(callbackUrl)}`;

  async function acceptInvitation() {
    if (!session?.accessToken) return;
    setAccepting(true);
    setError("");
    setAccountMismatch(false);

    try {
      const response = await fetch(`${API_URL}/workspaces/invitations/accept`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${session.accessToken}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ token }),
      });
      const body = (await response.json().catch(() => null)) as
        | WorkspaceSummary
        | { detail?: string }
        | null;

      if (!response.ok) {
        const detail =
          body && "detail" in body && typeof body.detail === "string"
            ? body.detail
            : "Invitation could not be accepted.";
        setError(detail);
        setAccountMismatch(
          response.status === 403 || detail.toLowerCase().includes("email address"),
        );
        return;
      }

      const workspace = body as WorkspaceSummary;
      await update({ workspaceId: workspace.id });
      window.location.assign("/");
    } catch {
      setError("Unable to reach the workspace service.");
    } finally {
      setAccepting(false);
    }
  }

  async function switchAccount() {
    setSwitching(true);
    await signOut({ callbackUrl: loginUrl });
  }

  return (
    <div className="operator-grid flex min-h-screen items-center justify-center bg-[#f9f7f3] px-4 py-10 text-[#202020]">
      <div className="w-full max-w-lg overflow-hidden rounded-[24px] border border-[rgba(32,32,32,0.12)] bg-white">
        <div className="border-b border-[rgba(32,32,32,0.1)] bg-[#f3f0e8] px-6 py-8 text-center sm:px-10">
          <div className="mx-auto grid h-12 w-12 place-items-center rounded-full bg-[#202020] text-white">
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
              <circle cx="9" cy="7" r="4" />
              <path d="M19 8v6M22 11h-6" />
            </svg>
          </div>
          <p className="mt-5 text-xs font-semibold uppercase tracking-[0.16em] text-[#646464]">
            Team access
          </p>
          <h1 className="mt-2 text-3xl font-semibold tracking-[-0.045em] sm:text-4xl">
            Workspace invitation
          </h1>
          <p className="mx-auto mt-3 max-w-sm text-sm leading-6 text-[#646464]">
            Continue with the exact email address selected by the workspace owner.
          </p>
        </div>

        <div className="p-6 sm:p-8">
          {status === "loading" && (
            <div className="space-y-3">
              <div className="h-16 animate-pulse rounded-2xl bg-[#f3f0e8]" />
              <div className="h-12 animate-pulse rounded-full bg-[#f3f0e8]" />
            </div>
          )}

          {status === "unauthenticated" && (
            <div className="space-y-3">
              <Link
                href={loginUrl}
                className="flex min-h-12 w-full items-center justify-center rounded-full bg-[#ea2804] px-5 text-center text-sm font-semibold text-white transition hover:bg-[#c01f00]"
              >
                Sign in to accept
              </Link>
              <Link
                href={registerUrl}
                className="flex min-h-12 w-full items-center justify-center rounded-full border border-[#202020] px-5 text-center text-sm font-semibold text-[#202020] transition hover:bg-[#202020] hover:text-white"
              >
                Create invited account
              </Link>
            </div>
          )}

          {status === "authenticated" && (
            <div>
              <div className="rounded-2xl border border-[rgba(32,32,32,0.1)] bg-[#f9f7f3] p-4">
                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#646464]">Currently signed in</p>
                <p className="mt-2 break-all font-semibold text-[#202020]">{session.user?.email}</p>
              </div>

              {error && (
                <div className="mt-4 rounded-2xl border border-red-200 bg-red-50 p-4 text-sm leading-6 text-red-800">
                  <p className="font-semibold">
                    {accountMismatch ? "This invitation belongs to another account" : "Invitation could not be accepted"}
                  </p>
                  <p className="mt-1">{error}</p>
                </div>
              )}

              {accountMismatch ? (
                <div className="mt-5 space-y-3">
                  <button
                    type="button"
                    onClick={switchAccount}
                    disabled={switching}
                    className="min-h-12 w-full rounded-full bg-[#ea2804] px-5 text-sm font-semibold text-white transition hover:bg-[#c01f00] disabled:opacity-50"
                  >
                    {switching ? "Switching account…" : "Switch account"}
                  </button>
                  <p className="text-center text-xs leading-5 text-[#646464]">
                    You will return to this invitation after signing in with the invited email.
                  </p>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={acceptInvitation}
                  disabled={accepting || !session.accessToken}
                  className="mt-5 min-h-12 w-full rounded-full bg-[#ea2804] px-5 text-sm font-semibold text-white transition hover:bg-[#c01f00] disabled:opacity-50"
                >
                  {accepting ? "Accepting invitation…" : "Accept invitation"}
                </button>
              )}

              {!accountMismatch && (
                <button
                  type="button"
                  onClick={switchAccount}
                  disabled={switching}
                  className="mt-3 min-h-11 w-full rounded-full border border-[rgba(32,32,32,0.18)] px-5 text-sm font-semibold text-[#202020] transition hover:border-[#202020] hover:bg-[#202020] hover:text-white disabled:opacity-50"
                >
                  {switching ? "Signing out…" : "Use a different account"}
                </button>
              )}
            </div>
          )}

          <Link href="/" className="mt-6 block text-center text-sm font-semibold text-[#646464] hover:text-[#202020]">
            Return to dashboard
          </Link>
        </div>
      </div>
    </div>
  );
}
