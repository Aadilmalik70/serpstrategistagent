"use client";

import { signIn, useSession } from "next-auth/react";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function OAuthCompletePage() {
  const { data: session, status } = useSession();
  const searchParams = useSearchParams();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const callbackUrl = useMemo(() => {
    const requested = searchParams.get("callbackUrl");
    return requested?.startsWith("/") && !requested.startsWith("//") ? requested : "/";
  }, [searchParams]);

  useEffect(() => {
    if (status === "authenticated" && session?.accessToken && !session.oauthLinkRequired) {
      window.location.replace(callbackUrl);
    }
    if (status === "unauthenticated") {
      window.location.replace(`/login?callbackUrl=${encodeURIComponent(callbackUrl)}`);
    }
  }, [callbackUrl, session, status]);

  async function confirmLink(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session?.oauthLinkToken || !session.oauthLinkEmail) {
      setError("The account-link request is missing or expired. Start social sign-in again.");
      return;
    }

    setLoading(true);
    setError("");
    const formData = new FormData(event.currentTarget);
    const password = String(formData.get("password") || "");

    try {
      const response = await fetch(`${API_URL}/auth/oauth/link`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: session.oauthLinkToken, password }),
      });
      const body = (await response.json().catch(() => null)) as
        | { user?: { email?: string }; detail?: string }
        | null;
      if (!response.ok) {
        setError(body?.detail || "The provider account could not be linked.");
        return;
      }

      const email = body?.user?.email || session.oauthLinkEmail;
      const result = await signIn("credentials", {
        email,
        password,
        redirect: false,
      });
      if (result?.error) {
        setError("The provider was linked, but the new session could not be created. Sign in again.");
        return;
      }
      window.location.replace(callbackUrl);
    } catch {
      setError("Unable to reach the authentication service.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="operator-grid flex min-h-screen items-center justify-center bg-[#f9f7f3] px-4 py-10 text-[#202020]">
      <div className="w-full max-w-md overflow-hidden rounded-[24px] border border-[rgba(32,32,32,0.12)] bg-white">
        <div className="border-b border-[rgba(32,32,32,0.1)] bg-[#f3f0e8] px-7 py-8 text-center">
          <div className="mx-auto grid h-12 w-12 place-items-center rounded-full bg-[#202020] text-white">✓</div>
          <h1 className="mt-5 text-3xl font-semibold tracking-[-0.045em]">
            {session?.oauthLinkRequired ? "Confirm account linking" : "Completing sign-in"}
          </h1>
          <p className="mt-2 text-sm leading-6 text-[#646464]">
            {session?.oauthLinkRequired
              ? "A password account already uses this email. Confirm its password before linking the provider."
              : "Your verified provider identity is being connected to the operator."}
          </p>
        </div>

        <div className="p-7">
          {(status === "loading" || (session?.accessToken && !session.oauthLinkRequired)) && (
            <div className="space-y-3">
              <div className="h-16 animate-pulse rounded-2xl bg-[#f3f0e8]" />
              <p className="text-center text-sm text-[#646464]">Preparing your workspace…</p>
            </div>
          )}

          {status === "authenticated" && session?.oauthLinkRequired && (
            <form onSubmit={confirmLink}>
              <div className="rounded-2xl border border-[rgba(32,32,32,0.1)] bg-[#f9f7f3] p-4">
                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#646464]">Existing account</p>
                <p className="mt-2 break-all font-semibold">{session.oauthLinkEmail}</p>
              </div>

              <label htmlFor="link-password" className="mt-5 block text-sm font-semibold">Account password</label>
              <input
                id="link-password"
                name="password"
                type="password"
                required
                autoComplete="current-password"
                className="mt-2 h-12 w-full rounded-full border border-[rgba(32,32,32,0.18)] bg-white px-5 text-[#202020]"
              />

              {error && (
                <div className="mt-4 rounded-2xl border border-red-200 bg-red-50 p-4 text-sm leading-6 text-red-800">
                  {error}
                </div>
              )}

              <button
                type="submit"
                disabled={loading}
                className="mt-5 min-h-12 w-full rounded-full bg-[#ea2804] px-5 text-sm font-semibold text-white transition hover:bg-[#c01f00] disabled:opacity-50"
              >
                {loading ? "Linking provider…" : "Confirm and link provider"}
              </button>
              <p className="mt-4 text-center text-xs leading-5 text-[#646464]">
                The provider cannot access your password. It is sent only to the SERP Strategists API for this confirmation.
              </p>
            </form>
          )}

          {status === "authenticated" && !session?.accessToken && !session?.oauthLinkRequired && (
            <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm leading-6 text-red-800">
              Social sign-in did not return an operator session. Return to login and try again.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
