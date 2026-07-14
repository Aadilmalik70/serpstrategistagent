import AuditClaimClient from "@/components/audits/audit-claim-client";

export default async function AuditClaimPage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string; site?: string }>;
}) {
  const params = await searchParams;
  const token = params.token?.trim() || "";
  const requestedSite = params.site?.trim().slice(0, 255) || undefined;

  return <AuditClaimClient token={token} requestedSite={requestedSite} />;
}
