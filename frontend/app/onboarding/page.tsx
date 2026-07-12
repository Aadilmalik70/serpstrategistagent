"use client";

import { useSession } from "next-auth/react";
import { FormEvent, useMemo, useState } from "react";
import useSWR from "swr";

import { apiFetch, OperatorApiError } from "@/lib/api";

type StepId = "profile" | "site" | "cms" | "google" | "goals" | "review";

type OnboardingState = {
  id: string;
  workspace_id: string;
  user_id: string;
  onboarding_version: number;
  current_step: StepId;
  completed_steps: StepId[];
  answers: Record<string, Record<string, unknown>>;
  status: string;
  completion_percent: number;
};

const steps: { id: StepId; label: string; eyebrow: string }[] = [
  { id: "profile", label: "About you", eyebrow: "01" },
  { id: "site", label: "Your site", eyebrow: "02" },
  { id: "cms", label: "CMS", eyebrow: "03" },
  { id: "google", label: "Google data", eyebrow: "04" },
  { id: "goals", label: "Goals", eyebrow: "05" },
  { id: "review", label: "Launch", eyebrow: "06" },
];

function nextStep(step: StepId): StepId {
  const index = steps.findIndex((item) => item.id === step);
  return steps[Math.min(index + 1, steps.length - 1)].id;
}

function previousStep(step: StepId): StepId {
  const index = steps.findIndex((item) => item.id === step);
  return steps[Math.max(index - 1, 0)].id;
}

export default function OnboardingPage() {
  const { data: session } = useSession();
  const { data, error, mutate, isLoading } = useSWR<OnboardingState>(
    session?.accessToken && session.workspaceId ? "/onboarding" : null,
    apiFetch,
  );
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [localStep, setLocalStep] = useState<StepId | null>(null);

  const currentStep = localStep || data?.current_step || "profile";
  const currentIndex = steps.findIndex((item) => item.id === currentStep);
  const answers = data?.answers?.[currentStep] || {};

  async function saveStep(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setMessage("");
    const form = new FormData(event.currentTarget);
    const values: Record<string, unknown> = {};

    for (const [key, value] of form.entries()) {
      if (key === "priorities") {
        const priorities = form.getAll("priorities").map(String);
        values.priorities = priorities;
      } else {
        values[key] = String(value);
      }
    }

    try {
      const updated = await apiFetch<OnboardingState>("/onboarding/step", {
        method: "PUT",
        body: JSON.stringify({
          step: currentStep,
          answers: values,
          complete_step: true,
          next_step: nextStep(currentStep),
        }),
      });
      await mutate(updated, false);
      setLocalStep(updated.current_step);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (requestError) {
      setMessage(requestError instanceof OperatorApiError ? requestError.message : "Could not save this step.");
    } finally {
      setSaving(false);
    }
  }

  async function skipStep() {
    setSaving(true);
    setMessage("");
    try {
      const updated = await apiFetch<OnboardingState>("/onboarding/step", {
        method: "PUT",
        body: JSON.stringify({
          step: currentStep,
          answers: { skipped: true },
          complete_step: true,
          next_step: nextStep(currentStep),
        }),
      });
      await mutate(updated, false);
      setLocalStep(updated.current_step);
    } catch (requestError) {
      setMessage(requestError instanceof OperatorApiError ? requestError.message : "Could not skip this step.");
    } finally {
      setSaving(false);
    }
  }

  async function launchOperator() {
    setSaving(true);
    setMessage("");
    try {
      await apiFetch<OnboardingState>("/onboarding/complete", {
        method: "POST",
        body: JSON.stringify({ launch_operator: true }),
      });
      window.location.assign("/");
    } catch (requestError) {
      setMessage(requestError instanceof OperatorApiError ? requestError.message : "Could not launch the operator.");
      setSaving(false);
    }
  }

  if (isLoading || !data) {
    return (
      <div className="grid min-h-screen place-items-center bg-[#f9f7f3] text-[#202020]">
        <div className="text-center">
          <div className="mx-auto h-12 w-12 animate-pulse rounded-full bg-[#ea2804]" />
          <p className="mt-4 text-sm text-[#646464]">Preparing your growth operator…</p>
        </div>
      </div>
    );
  }

  if (error) {
    return <div className="grid min-h-screen place-items-center bg-[#f9f7f3] p-6 text-red-700">Unable to load onboarding.</div>;
  }

  return (
    <div className="min-h-screen bg-[#f9f7f3] text-[#202020]">
      <header className="border-b border-[rgba(32,32,32,0.12)] bg-[#f9f7f3]">
        <div className="mx-auto flex min-h-[72px] max-w-7xl items-center justify-between gap-4 px-4 sm:px-6 lg:px-8">
          <div className="flex items-center gap-3">
            <span className="grid h-10 w-10 place-items-center rounded-full bg-[#ea2804] font-bold text-white">S</span>
            <div>
              <p className="font-semibold">SERP Strategists</p>
              <p className="text-xs text-[#646464]">Operator setup</p>
            </div>
          </div>
          <div className="text-right">
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#646464]">Progress</p>
            <p className="text-sm font-semibold">{data.completion_percent}% complete</p>
          </div>
        </div>
      </header>

      <main className="mx-auto grid max-w-7xl gap-8 px-4 py-8 sm:px-6 lg:grid-cols-[280px_minmax(0,1fr)] lg:px-8 lg:py-12">
        <aside className="lg:sticky lg:top-8 lg:self-start">
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#646464]">Setup journey</p>
          <div className="mt-4 space-y-2">
            {steps.map((step, index) => {
              const active = step.id === currentStep;
              const complete = data.completed_steps.includes(step.id);
              return (
                <button
                  key={step.id}
                  type="button"
                  onClick={() => setLocalStep(step.id)}
                  className={`flex w-full items-center gap-3 rounded-2xl px-3 py-3 text-left transition ${active ? "bg-[#202020] text-white" : "hover:bg-[#f3f0e8]"}`}
                >
                  <span className={`grid h-8 w-8 shrink-0 place-items-center rounded-full text-xs font-semibold ${active ? "bg-[#ea2804] text-white" : complete ? "bg-[#2b9a66] text-white" : "bg-white text-[#646464]"}`}>
                    {complete ? "✓" : step.eyebrow}
                  </span>
                  <span>
                    <span className="block text-sm font-semibold">{step.label}</span>
                    <span className={`text-xs ${active ? "text-white/60" : "text-[#8d8d8d]"}`}>Step {index + 1} of {steps.length}</span>
                  </span>
                </button>
              );
            })}
          </div>
        </aside>

        <section className="overflow-hidden rounded-[24px] border border-[rgba(32,32,32,0.12)] bg-white">
          <div className="operator-grid border-b border-[rgba(32,32,32,0.1)] bg-[#f3f0e8] px-6 py-8 sm:px-10 sm:py-12">
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#646464]">{steps[currentIndex]?.label}</p>
            <h1 className="mt-3 max-w-3xl text-[clamp(2.4rem,7vw,4.6rem)] font-semibold leading-[0.96] tracking-[-0.055em]">
              {currentStep === "profile" && "Tell us who the operator is working for."}
              {currentStep === "site" && "Add the website that should grow."}
              {currentStep === "cms" && "Choose where approved changes can ship."}
              {currentStep === "google" && "Connect search and traffic truth."}
              {currentStep === "goals" && "Define what progress should mean."}
              {currentStep === "review" && "Review the setup, then launch."}
            </h1>
          </div>

          <div className="p-6 sm:p-10">
            {message && <div className="mb-6 rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">{message}</div>}

            {currentStep === "review" ? (
              <div>
                <div className="grid gap-4 sm:grid-cols-2">
                  {steps.slice(0, -1).map((step) => (
                    <div key={step.id} className="rounded-2xl border border-[rgba(32,32,32,0.1)] bg-[#f9f7f3] p-5">
                      <div className="flex items-center justify-between gap-3">
                        <p className="font-semibold">{step.label}</p>
                        <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${data.completed_steps.includes(step.id) ? "bg-[#2b9a66] text-white" : "bg-[#f3f0e8] text-[#646464]"}`}>
                          {data.completed_steps.includes(step.id) ? "Ready" : "Incomplete"}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
                <button onClick={launchOperator} disabled={saving} className="mt-8 min-h-12 w-full rounded-full bg-[#ea2804] px-6 text-sm font-semibold text-white hover:bg-[#c01f00] disabled:opacity-50 sm:w-auto">
                  {saving ? "Launching…" : "Launch my growth operator"}
                </button>
              </div>
            ) : (
              <form onSubmit={saveStep} className="space-y-5">
                {currentStep === "profile" && (
                  <>
                    <Field name="full_name" label="Full name" defaultValue={answers.full_name} required />
                    <Field name="company_name" label="Company or brand" defaultValue={answers.company_name} required />
                    <Select name="role" label="Your role" defaultValue={answers.role} options={["Founder", "Marketer", "SEO", "Agency", "Developer"]} />
                    <Select name="business_type" label="Business type" defaultValue={answers.business_type} options={["SaaS", "E-commerce", "Agency", "Publisher", "Local business"]} />
                    <div className="grid gap-4 sm:grid-cols-2">
                      <Field name="country" label="Primary country" defaultValue={answers.country} required />
                      <Field name="timezone" label="Timezone" defaultValue={answers.timezone} placeholder="Asia/Kolkata" required />
                    </div>
                  </>
                )}

                {currentStep === "site" && (
                  <>
                    <Field name="website_url" label="Website URL" defaultValue={answers.website_url} placeholder="https://example.com" type="url" required />
                    <Field name="site_name" label="Display name" defaultValue={answers.site_name} required />
                    <div className="grid gap-4 sm:grid-cols-2">
                      <Field name="primary_market" label="Primary market" defaultValue={answers.primary_market} />
                      <Field name="language" label="Preferred language" defaultValue={answers.language} placeholder="English" />
                    </div>
                  </>
                )}

                {currentStep === "cms" && (
                  <div className="grid gap-4 sm:grid-cols-2">
                    <ConnectorCard name="cms" value="github" title="GitHub" description="For Next.js, React and custom repositories." defaultChecked={answers.cms === "github"} />
                    <ConnectorCard name="cms" value="wordpress" title="WordPress" description="For WordPress sites using application passwords." defaultChecked={answers.cms === "wordpress"} />
                  </div>
                )}

                {currentStep === "google" && (
                  <div className="rounded-[20px] border border-[rgba(32,32,32,0.1)] bg-[#f9f7f3] p-6">
                    <p className="text-lg font-semibold">Google Search Console + GA4</p>
                    <p className="mt-2 text-sm leading-6 text-[#646464]">The secure OAuth connector is being wired next. Saving this step preserves your place through the redirect.</p>
                    <input type="hidden" name="connection_intent" value="google_search_and_analytics" />
                  </div>
                )}

                {currentStep === "goals" && (
                  <div className="grid gap-3 sm:grid-cols-2">
                    {["Increase organic traffic", "Fix technical SEO", "Grow AI-search visibility", "Increase conversions", "Recover declining rankings", "Publish programmatic SEO", "Track competitors"].map((goal) => (
                      <label key={goal} className="flex cursor-pointer items-center gap-3 rounded-2xl border border-[rgba(32,32,32,0.12)] p-4 hover:bg-[#f9f7f3]">
                        <input type="checkbox" name="priorities" value={goal} defaultChecked={Array.isArray(answers.priorities) && answers.priorities.includes(goal)} className="h-4 w-4" />
                        <span className="text-sm font-semibold">{goal}</span>
                      </label>
                    ))}
                  </div>
                )}

                <div className="flex flex-col-reverse gap-3 border-t border-[rgba(32,32,32,0.1)] pt-6 sm:flex-row sm:items-center sm:justify-between">
                  <button type="button" onClick={() => setLocalStep(previousStep(currentStep))} disabled={currentIndex === 0 || saving} className="min-h-11 rounded-full border border-[rgba(32,32,32,0.18)] px-5 text-sm font-semibold disabled:opacity-40">
                    Back
                  </button>
                  <div className="flex flex-col gap-3 sm:flex-row">
                    {(currentStep === "cms" || currentStep === "google") && (
                      <button type="button" onClick={skipStep} disabled={saving} className="min-h-11 rounded-full px-5 text-sm font-semibold text-[#646464]">Skip for now</button>
                    )}
                    <button disabled={saving} className="min-h-12 rounded-full bg-[#ea2804] px-6 text-sm font-semibold text-white hover:bg-[#c01f00] disabled:opacity-50">
                      {saving ? "Saving…" : "Save and continue"}
                    </button>
                  </div>
                </div>
              </form>
            )}
          </div>
        </section>
      </main>
    </div>
  );
}

function Field({ name, label, defaultValue, required, placeholder, type = "text" }: { name: string; label: string; defaultValue?: unknown; required?: boolean; placeholder?: string; type?: string }) {
  return (
    <label className="block">
      <span className="text-sm font-semibold">{label}</span>
      <input name={name} type={type} defaultValue={typeof defaultValue === "string" ? defaultValue : ""} required={required} placeholder={placeholder} className="mt-2 h-12 w-full rounded-full border border-[rgba(32,32,32,0.18)] bg-white px-5 text-[#202020]" />
    </label>
  );
}

function Select({ name, label, defaultValue, options }: { name: string; label: string; defaultValue?: unknown; options: string[] }) {
  return (
    <label className="block">
      <span className="text-sm font-semibold">{label}</span>
      <select name={name} defaultValue={typeof defaultValue === "string" ? defaultValue : ""} required className="mt-2 h-12 w-full rounded-full border border-[rgba(32,32,32,0.18)] bg-white px-5 text-[#202020]">
        <option value="" disabled>Select one</option>
        {options.map((option) => <option key={option} value={option.toLowerCase().replaceAll(" ", "_")}>{option}</option>)}
      </select>
    </label>
  );
}

function ConnectorCard({ name, value, title, description, defaultChecked }: { name: string; value: string; title: string; description: string; defaultChecked: boolean }) {
  return (
    <label className="cursor-pointer rounded-[20px] border border-[rgba(32,32,32,0.12)] p-5 transition hover:bg-[#f9f7f3]">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-lg font-semibold">{title}</p>
          <p className="mt-2 text-sm leading-6 text-[#646464]">{description}</p>
        </div>
        <input type="radio" name={name} value={value} defaultChecked={defaultChecked} required className="mt-1 h-4 w-4" />
      </div>
    </label>
  );
}
