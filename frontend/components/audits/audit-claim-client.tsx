"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { apiFetch, OperatorApiError } from "@/lib/api";

type ClaimResponse = {
  site_id: string;
  domain: string;
  crawl_job_id: string;
  crawl_status: string;
  reused_site: boolean;
  reused_crawl: boolean;
  claimed_at: string;
};

const AUDIT_TOKEN = /^[A-Za-z0-9_-]{20,64}$/;

export default function AuditClaimClient({
  token,
  requestedSite,
}: {
  token: string;
  requestedSite?: string;
}) {
  const router = useRouter();
  const started = useRef(false);
  const [attempt, setAttempt] = useState(0);
  const tokenValid = AUDIT_TOKEN.test(token);
  const [error, setError] = useState(
    tokenValid ? "" : "This audit link is invalid or incomplete.",
  );

  useEffect(() => {
    if (started.current) return;
    if (!tokenValid) return;

    started.current = true;
    let active = true;

    async function claim() {
      try {
        const result = await apiFetch<ClaimResponse>(
          `/public/audits/${encodeURIComponent(token)}/claim`,
          { method: "POST" },
        );
        if (!active) return;
        router.replace(`/sites/${result.site_id}?source=free-audit`);
        router.refresh();
      } catch (claimError) {
        if (!active) return;
        setError(
          claimError instanceof OperatorApiError
            ? claimError.message
            : "The full audit could not be unlocked. Try again.",
        );
      }
    }

    void claim();
    return () => {
      active = false;
    };
  }, [attempt, router, token, tokenValid]);

  function retry() {
    started.current = false;
    setError("");
    setAttempt((value) => value + 1);
  }

  return (
    <main className="operator-grid flex min-h-screen items-center justify-center bg-[#f9f7f3] px-4 py-10 text-[#202020]">
      <section className="w-full max-w-lg overflow-hidden rounded-[24px] border border-[rgba(32,32,32,0.12)] bg-white shadow-sm">
        <div className="border-b border-[rgba(32,32,32,0.1)] bg-[#f3f0e8] px-7 py-8 text-center">
          <div className="mx-auto grid h-12 w-12 place-items-center rounded-full bg-[#ea2804] font-bold text-white">
            {error ? "!" : "S"}
          </div>
          <p className="mt-5 text-xs font-semibold uppercase tracking-[0.16em] text-[#646464]">
            Free audit handoff
          </p>
          <h1 className="mt-2 text-3xl font-semibold tracking-[-0.045em]">
            {error ? "We couldn’t unlock the audit" : "Preparing your full site audit"}
          </h1>
          <p className="mt-2 text-sm leading-6 text-[#646464]">
            {requestedSite
              ? `Claiming ${requestedSite} and starting the first-party crawler.`
              : "Claiming the audited site and starting the first-party crawler."}
          </p>
        </div>

        <div className="p-7" aria-live="polite">
          {error ? (
            <div>
              <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm leading-6 text-red-800">
                {error}
              </div>
              <div className="mt-5 flex flex-col gap-3 sm:flex-row">
                <button
                  type="button"
                  onClick={retry}
                  className="min-h-11 flex-1 rounded-full bg-[#202020] px-5 text-sm font-semibold text-white"
                >
                  Try again
                </button>
                <Link
                  href="/"
                  className="flex min-h-11 flex-1 items-center justify-center rounded-full border border-[rgba(32,32,32,0.18)] px-5 text-sm font-semibold"
                >
                  Open dashboard
                </Link>
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              {["Verify audit token", "Create or reuse your site", "Queue first-party crawl"].map(
                (step) => (
                  <div
                    key={step}
                    className="flex items-center gap-3 rounded-2xl border border-[rgba(32,32,32,0.1)] bg-[#f9f7f3] px-4 py-3 text-sm text-[#646464]"
                  >
                    <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-[#ea2804]" />
                    {step}
                  </div>
                ),
              )}
              <p className="text-center text-xs leading-5 text-[#646464]">
                You’ll be redirected to the site workspace as soon as the crawl is queued.
              </p>
            </div>
          )}
        </div>
      </section>
    </main>
  );
}
