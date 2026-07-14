"use client";

import { SessionProvider, useSession } from "next-auth/react";
import { useEffect, type ReactNode } from "react";

import OnboardingGate from "@/components/onboarding/onboarding-gate";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const ONBOARDING_ENABLED = process.env.NEXT_PUBLIC_ONBOARDING_ENABLED === "true";

function AuthenticatedApiTransport({ children }: { children: ReactNode }) {
  const { data: session } = useSession();

  useEffect(() => {
    const originalFetch = window.fetch.bind(window);

    window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      const requestUrl =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.toString()
            : input.url;

      if (!requestUrl.startsWith(API_BASE)) {
        return originalFetch(input, init);
      }

      const headers = new Headers(input instanceof Request ? input.headers : init?.headers);
      if (session?.accessToken && session.workspaceId) {
        headers.set("Authorization", `Bearer ${session.accessToken}`);
        headers.set("X-Workspace-ID", session.workspaceId);
      }

      return originalFetch(input, { ...init, headers });
    };

    return () => {
      window.fetch = originalFetch;
    };
  }, [session?.accessToken, session?.workspaceId]);

  return children;
}

function OptionalOnboardingGate({ children }: { children: ReactNode }) {
  if (!ONBOARDING_ENABLED) return children;
  return <OnboardingGate>{children}</OnboardingGate>;
}

export default function Providers({ children }: { children: ReactNode }) {
  return (
    <SessionProvider>
      <AuthenticatedApiTransport>
        <OptionalOnboardingGate>{children}</OptionalOnboardingGate>
      </AuthenticatedApiTransport>
    </SessionProvider>
  );
}
