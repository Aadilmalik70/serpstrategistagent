"use client";

import { usePathname, useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { useEffect, type ReactNode } from "react";
import useSWR from "swr";

import { apiFetch } from "@/lib/api";

type OnboardingStatus = {
  current_step: string;
  status: string;
};

const PUBLIC_PREFIXES = ["/login", "/register", "/invite", "/auth/"];

export default function OnboardingGate({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { data: session, status: sessionStatus } = useSession();
  const isOwnerOrAdmin = session?.workspaceRole === "owner" || session?.workspaceRole === "admin";
  const isPublic = PUBLIC_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(prefix));
  const shouldCheck =
    sessionStatus === "authenticated" &&
    Boolean(session?.accessToken && session.workspaceId) &&
    isOwnerOrAdmin &&
    !isPublic;

  const { data, isLoading } = useSWR<OnboardingStatus>(shouldCheck ? "/onboarding" : null, apiFetch, {
    revalidateOnFocus: false,
  });

  useEffect(() => {
    if (!shouldCheck || !data) return;
    if (data.status !== "completed" && pathname !== "/onboarding") {
      router.replace(`/onboarding?step=${encodeURIComponent(data.current_step || "profile")}`);
      return;
    }
    if (data.status === "completed" && pathname === "/onboarding") {
      const editMode = new URLSearchParams(window.location.search).get("edit") === "1";
      if (!editMode) router.replace("/");
    }
  }, [data, pathname, router, shouldCheck]);

  if (shouldCheck && isLoading && pathname !== "/onboarding") {
    return (
      <div className="grid min-h-screen place-items-center bg-[#f9f7f3] text-[#202020]">
        <div className="text-center">
          <div className="mx-auto h-10 w-10 animate-pulse rounded-full bg-[#ea2804]" />
          <p className="mt-4 text-sm text-[#646464]">Restoring your operator setup…</p>
        </div>
      </div>
    );
  }

  return children;
}
