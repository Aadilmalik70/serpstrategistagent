"use client";

import { FormEvent, useState } from "react";

import { apiFetch, OperatorApiError } from "@/lib/api";

interface AddSiteFormProps {
  onSuccess: (siteId: string, jobId?: string) => void;
}

type CreatedSite = { id: string };
type CrawlJob = { job_id: string };
type ClaimStart = {
  site_id: string;
  domain: string;
  method: string;
  record_name: string;
  record_value: string;
  expires_at: string;
};

export default function AddSiteForm({ onSuccess }: AddSiteFormProps) {
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [claimLoading, setClaimLoading] = useState(false);
  const [claimDomain, setClaimDomain] = useState("");
  const [claim, setClaim] = useState<ClaimStart | null>(null);

  async function startCrawl(siteId: string) {
    try {
      const job = await apiFetch<CrawlJob>("/crawl/site", {
        method: "POST",
        body: JSON.stringify({ site_id: siteId }),
      });
      onSuccess(siteId, job.job_id);
    } catch {
      onSuccess(siteId);
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");
    setClaim(null);
    setClaimDomain("");

    const formData = new FormData(event.currentTarget);
    const domain = formData.get("domain") as string;
    const name = formData.get("name") as string;

    try {
      const site = await apiFetch<CreatedSite>("/sites", {
        method: "POST",
        body: JSON.stringify({ domain, name: name || undefined }),
      });
      await startCrawl(site.id);
    } catch (requestError) {
      if (requestError instanceof OperatorApiError) {
        if (requestError.status === 409) {
          setClaimDomain(domain);
          setError(
            "This domain already exists. Verify ownership to claim the existing site for your workspace.",
          );
        } else {
          setError(requestError.message);
        }
      } else {
        setError("Network error. Please try again.");
      }
      setLoading(false);
    }
  }

  async function beginClaim() {
    setClaimLoading(true);
    setError("");
    try {
      const result = await apiFetch<ClaimStart>("/sites/claims/start", {
        method: "POST",
        body: JSON.stringify({ domain: claimDomain }),
      });
      setClaim(result);
    } catch (requestError) {
      setError(
        requestError instanceof OperatorApiError
          ? requestError.message
          : "Could not start ownership verification.",
      );
    } finally {
      setClaimLoading(false);
    }
  }

  async function verifyClaim() {
    if (!claim) return;
    setClaimLoading(true);
    setError("");
    try {
      const site = await apiFetch<CreatedSite>("/sites/claims/verify", {
        method: "POST",
        body: JSON.stringify({
          domain: claim.domain,
          token: claim.record_value,
        }),
      });
      await startCrawl(site.id);
    } catch (requestError) {
      setError(
        requestError instanceof OperatorApiError
          ? requestError.message
          : "Could not verify the DNS record.",
      );
      setClaimLoading(false);
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

      {claimDomain && !claim && (
        <button
          type="button"
          onClick={beginClaim}
          disabled={claimLoading}
          className="w-full py-2 px-4 border border-blue-600 text-blue-700 rounded-md hover:bg-blue-50 disabled:opacity-50 font-medium"
        >
          {claimLoading ? "Preparing verification..." : "Verify Ownership & Claim Site"}
        </button>
      )}

      {claim && (
        <div className="rounded-lg border border-blue-200 bg-blue-50 p-4 space-y-3 text-sm">
          <div>
            <p className="font-semibold text-blue-950">Add this DNS TXT record</p>
            <p className="text-blue-800 mt-1">
              Add the record in the DNS settings for <strong>{claim.domain}</strong>. It expires at{" "}
              {new Date(claim.expires_at).toLocaleString()}.
            </p>
          </div>
          <div>
            <p className="text-xs font-medium text-blue-900">Name / Host</p>
            <code className="block mt-1 break-all rounded bg-white p-2 border border-blue-100">
              {claim.record_name}
            </code>
          </div>
          <div>
            <p className="text-xs font-medium text-blue-900">Value</p>
            <code className="block mt-1 break-all rounded bg-white p-2 border border-blue-100">
              {claim.record_value}
            </code>
          </div>
          <button
            type="button"
            onClick={verifyClaim}
            disabled={claimLoading}
            className="w-full py-2 px-4 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50 font-medium"
          >
            {claimLoading ? "Checking DNS..." : "Verify DNS & Claim Site"}
          </button>
        </div>
      )}

      <button
        type="submit"
        disabled={loading || claimLoading}
        className="w-full py-2 px-4 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50 font-medium"
      >
        {loading ? "Adding site..." : "Add Site & Start Crawl"}
      </button>
    </form>
  );
}
