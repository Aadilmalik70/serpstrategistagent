import OAuthButtons from "@/components/auth/oauth-buttons";
import SignInForm from "@/components/auth/sign-in-form";

const oauthErrorMessages: Record<string, string> = {
  OAuthEmailUnverified: "The provider did not return a verified email address.",
  GitHubEmailPermission:
    "GitHub did not grant access to your verified email. Re-authorize SERP Strategists with the user:email permission.",
  GitHubEmailUnverified:
    "Your GitHub account has no verified email address. Verify an email in GitHub Settings → Emails, then try again.",
  GitHubEmailUnavailable:
    "GitHub's email service could not be reached for this sign-in. Try again in a moment.",
  OAuthEmailUnavailable: "A verified GitHub email could not be read for this account.",
  OAuthSignin: "Social sign-in could not be completed. Check the provider configuration and try again.",
};

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ callbackUrl?: string; error?: string }>;
}) {
  const params = await searchParams;
  const requested = params.callbackUrl;
  const callbackUrl = requested?.startsWith("/") && !requested.startsWith("//") ? requested : "/";
  const googleEnabled = Boolean(process.env.GOOGLE_CLIENT_ID && process.env.GOOGLE_CLIENT_SECRET);
  const githubEnabled = Boolean(process.env.GITHUB_ID && process.env.GITHUB_SECRET);
  const oauthError = params.error ? oauthErrorMessages[params.error] : undefined;

  return (
    <div className="operator-grid flex min-h-screen items-center justify-center bg-[#f9f7f3] px-4 py-10 text-[#202020]">
      <div className="w-full max-w-md overflow-hidden rounded-[24px] border border-[rgba(32,32,32,0.12)] bg-white">
        <div className="border-b border-[rgba(32,32,32,0.1)] bg-[#f3f0e8] px-7 py-8 text-center">
          <div className="mx-auto grid h-12 w-12 place-items-center rounded-full bg-[#ea2804] font-bold text-white">S</div>
          <h1 className="mt-5 text-3xl font-semibold tracking-[-0.045em]">Welcome back</h1>
          <p className="mt-2 text-sm leading-6 text-[#646464]">Sign in to your governed growth workspace.</p>
        </div>

        <div className="p-7">
          {oauthError && (
            <div className="mb-5 rounded-2xl border border-red-200 bg-red-50 p-4 text-sm leading-6 text-red-800">
              {oauthError}
            </div>
          )}

          <OAuthButtons
            callbackUrl={callbackUrl}
            googleEnabled={googleEnabled}
            githubEnabled={githubEnabled}
          />

          {(googleEnabled || githubEnabled) && (
            <div className="my-6 flex items-center gap-3 text-xs font-semibold uppercase tracking-[0.14em] text-[#8d8d8d]">
              <span className="h-px flex-1 bg-[rgba(32,32,32,0.12)]" />
              Or use email
              <span className="h-px flex-1 bg-[rgba(32,32,32,0.12)]" />
            </div>
          )}

          <div className="flex justify-center">
            <SignInForm callbackUrl={callbackUrl} />
          </div>
        </div>
      </div>
    </div>
  );
}
