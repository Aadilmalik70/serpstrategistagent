"use client";

import { signIn } from "next-auth/react";
import { useState } from "react";

type OAuthButtonsProps = {
  callbackUrl: string;
  googleEnabled: boolean;
  githubEnabled: boolean;
};

export default function OAuthButtons({
  callbackUrl,
  googleEnabled,
  githubEnabled,
}: OAuthButtonsProps) {
  const [loading, setLoading] = useState<"google" | "github" | null>(null);
  const enabled = googleEnabled || githubEnabled;
  if (!enabled) return null;

  const completeUrl = `/auth/oauth-complete?callbackUrl=${encodeURIComponent(callbackUrl)}`;

  async function start(provider: "google" | "github") {
    setLoading(provider);
    await signIn(provider, { callbackUrl: completeUrl });
  }

  return (
    <div className="space-y-3">
      {googleEnabled && (
        <button
          type="button"
          onClick={() => start("google")}
          disabled={Boolean(loading)}
          className="flex min-h-12 w-full items-center justify-center gap-3 rounded-full border border-[rgba(32,32,32,0.18)] bg-white px-5 text-sm font-semibold text-[#202020] transition hover:border-[#202020] hover:bg-[#f3f0e8] disabled:opacity-50"
        >
          <span className="grid h-6 w-6 place-items-center rounded-full border border-[rgba(32,32,32,0.12)] text-xs font-bold">G</span>
          {loading === "google" ? "Connecting to Google…" : "Continue with Google"}
        </button>
      )}
      {githubEnabled && (
        <button
          type="button"
          onClick={() => start("github")}
          disabled={Boolean(loading)}
          className="flex min-h-12 w-full items-center justify-center gap-3 rounded-full bg-[#202020] px-5 text-sm font-semibold text-white transition hover:bg-black disabled:opacity-50"
        >
          <svg viewBox="0 0 24 24" className="h-5 w-5" fill="currentColor" aria-hidden="true">
            <path d="M12 .7a11.5 11.5 0 0 0-3.64 22.41c.58.1.79-.25.79-.56v-2.22c-3.22.7-3.9-1.37-3.9-1.37-.53-1.34-1.29-1.7-1.29-1.7-1.05-.72.08-.71.08-.71 1.16.08 1.78 1.2 1.78 1.2 1.04 1.77 2.72 1.26 3.38.96.1-.75.4-1.26.74-1.55-2.57-.29-5.27-1.28-5.27-5.68 0-1.26.45-2.28 1.19-3.09-.12-.29-.52-1.47.11-3.05 0 0 .97-.31 3.16 1.18A10.93 10.93 0 0 1 12 6.13c.98 0 1.95.13 2.86.39 2.2-1.49 3.16-1.18 3.16-1.18.63 1.58.23 2.76.11 3.05.74.81 1.19 1.83 1.19 3.09 0 4.41-2.71 5.38-5.29 5.67.42.36.79 1.07.79 2.16v3.24c0 .31.21.67.8.56A11.5 11.5 0 0 0 12 .7Z" />
          </svg>
          {loading === "github" ? "Connecting to GitHub…" : "Continue with GitHub"}
        </button>
      )}
    </div>
  );
}
