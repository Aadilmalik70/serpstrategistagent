import SignInForm from "@/components/auth/sign-in-form";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ callbackUrl?: string }>;
}) {
  const params = await searchParams;
  const requested = params.callbackUrl;
  const callbackUrl = requested?.startsWith("/") && !requested.startsWith("//") ? requested : "/";

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="p-8 bg-white rounded-lg shadow-md w-full max-w-md">
        <h1 className="text-2xl font-bold text-center mb-6">
          SERP Strategist Agent
        </h1>
        <p className="text-gray-600 text-center mb-8">
          Sign in to your account
        </p>
        <div className="flex justify-center">
          <SignInForm callbackUrl={callbackUrl} />
        </div>
      </div>
    </div>
  );
}
