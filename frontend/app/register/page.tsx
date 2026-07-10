import RegisterForm from "@/components/auth/register-form";

export default async function RegisterPage({
  searchParams,
}: {
  searchParams: Promise<{ callbackUrl?: string }>;
}) {
  const params = await searchParams;
  const requested = params.callbackUrl;
  const callbackUrl = requested?.startsWith("/") && !requested.startsWith("//") ? requested : "/";

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
      <div className="w-full max-w-md rounded-lg bg-white p-8 shadow-md">
        <h1 className="mb-2 text-center text-2xl font-bold">Create your SERP Strategists account</h1>
        <p className="mb-8 text-center text-gray-600">
          Your first Audit workspace is created automatically.
        </p>
        <div className="flex justify-center">
          <RegisterForm callbackUrl={callbackUrl} />
        </div>
      </div>
    </div>
  );
}
