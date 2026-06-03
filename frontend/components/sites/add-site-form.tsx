"use client";

import { FormEvent, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface AddSiteFormProps {
  onSuccess: (siteId: string, jobId?: string) => void;
}

export default function AddSiteForm({ onSuccess }: AddSiteFormProps) {
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setLoading(true);
    setError("");

    const formData = new FormData(e.currentTarget);
    const domain = formData.get("domain") as string;
    const name = formData.get("name") as string;

    try {
      // Create site
      const siteRes = await fetch(`${API_URL}/sites`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ domain, name: name || undefined }),
      });

      if (siteRes.status === 409) {
        setError("A site with this domain already exists");
        setLoading(false);
        return;
      }

      if (!siteRes.ok) {
        const err = await siteRes.json().catch(() => ({}));
        setError(err.detail || "Failed to add site");
        setLoading(false);
        return;
      }

      const site = await siteRes.json();

      // Start crawl
      const crawlRes = await fetch(`${API_URL}/crawl/site`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ site_id: site.id }),
      });

      if (crawlRes.ok) {
        const job = await crawlRes.json();
        onSuccess(site.id, job.job_id);
      } else {
        // Site created but crawl failed - still navigate
        onSuccess(site.id);
      }
    } catch {
      setError("Network error. Please try again.");
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
