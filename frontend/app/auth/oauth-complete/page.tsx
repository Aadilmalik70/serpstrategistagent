import OAuthCompleteClient from "@/components/auth/oauth-complete-client";

export default async function OAuthCompletePage({
  searchParams,
}: {
  searchParams: Promise<{ callbackUrl?: string }>;
}) {
  const params = await searchParams;
  const requested = params.callbackUrl;
  const callbackUrl = requested?.startsWith("/") && !requested.startsWith("//") ? requested : "/";

  return <OAuthCompleteClient callbackUrl={callbackUrl} />;
}
