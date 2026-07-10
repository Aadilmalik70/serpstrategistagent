"use client";

import { FormEvent, useState } from "react";

import { apiFetch, OperatorApiError } from "@/lib/api";

interface AddSiteFormProps {
  onSuccess: (siteId: string, jobId?: string) => void;
}

type CreatedSite = { id: string };
type CrawlJob = { job_id: string };

export default function AddSiteForm({ onSuccess }: AddSiteFormProps) {
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");

    const formData = new FormData(event.currentTarget);
    const domain = formData.get("domain") as string;
    const name = formData.get("name") as string;

    try {
      const site = await apiFetch<CreatedSite>("/sites", {
        method: "POST",
        body: JSON.stringify({ domain, name: name || undefined }),
      });

      try {
        const job = await apiFetch<CrawlJob>("/crawl/site", {
          method: "POST",
          body: JSON.stringify({ site_id: site.id }),
        });
        onSuccess(site.id, job.job_id);
      } catch {
        onSuccess(site.id);
      }
    } catch (requestError) {
      if (requestError instanceof OperatorApiError) {
        setError(
          requestError.status === 409
            ? "A site with this domain already exists"
            : requestError.message,
        );
      } else {
        setError("Network error. Please try again.");
      }
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <div>
        <label htmlFor="domain" className="block text-sm font-medium mb-1">
          Domain
        </label>
        <input
          id="domain"
          name="domain"
          type="text"
          required
          placeholder="example.com"
          className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <p className="text-xs text-gray-500 mt-1">
          Enter the domain without http:// or https://
        </p>
      </div>

      <div>
        <label htmlFor="name" className="block text-sm font-medium mb-1">
          Site Name (optional)
        </label>
        <input
          id="name"
          name="name"
          type="text"
          placeholder="My Website"
          className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>

      {error && <p className="text-red-600 text-sm">{error}</p>}

      <button
        type="submit"
        disabled={loading}
        className="w-full py-2 px-4 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50 font-medium"
      >
        {loading ? "Adding site..." : "Add Site & Start Crawl"}
      </button>
    </form>
  );
}
