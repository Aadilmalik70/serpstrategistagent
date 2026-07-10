"use client";

import Link from "next/link";
import { use, useState } from "react";
import { useSession } from "next-auth/react";

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

  const callbackUrl = `/invite/${encodeURIComponent(token)}`;

  async function acceptInvitation() {
    if (!session?.accessToken) return;
    setAccepting(true);
    setError("");

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
        setError(
          body && "detail" in body && typeof body.detail === "string"
            ? body.detail
            : "Invitation could not be accepted.",
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

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
      <div className="w-full max-w-md rounded-lg bg-white p-8 shadow-md">
        <h1 className="text-center text-2xl font-bold">Workspace invitation</h1>
        <p className="mt-2 text-center text-sm text-gray-600">
          Sign in using the exact email address that was invited.
        </p>

        {status === "loading" && (
          <div className="mt-8 h-12 animate-pulse rounded-md bg-gray-200" />
        )}

        {status === "unauthenticated" && (
          <div className="mt-8 space-y-3">
            <Link
              href={`/login?callbackUrl=${encodeURIComponent(callbackUrl)}`}
              className="block w-full rounded-md bg-blue-600 px-4 py-2 text-center font-medium text-white hover:bg-blue-700"
            >
              Sign in to accept
            </Link>
            <Link
              href={`/register?callbackUrl=${encodeURIComponent(callbackUrl)}`}
              className="block w-full rounded-md border border-gray-300 px-4 py-2 text-center font-medium text-gray-700 hover:bg-gray-50"
            >
              Create an account
            </Link>
          </div>
        )}

        {status === "authenticated" && (
          <div className="mt-8">
            <p className="rounded-md bg-gray-50 p-3 text-sm text-gray-700">
              Signed in as <strong>{session.user?.email}</strong>
            </p>
            {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
            <button
              type="button"
              onClick={acceptInvitation}
              disabled={accepting || !session.accessToken}
              className="mt-4 w-full rounded-md bg-blue-600 px-4 py-2 font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {accepting ? "Accepting invitation..." : "Accept invitation"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
