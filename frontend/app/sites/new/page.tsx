"use client";

import Link from "next/link";
import { useState } from "react";
import { useRouter } from "next/navigation";
import AddSiteForm from "@/components/sites/add-site-form";
import CrawlProgress from "@/components/sites/crawl-progress";

export default function NewSitePage() {
  const router = useRouter();
  const [siteId, setSiteId] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);

  function handleSiteCreated(id: string, crawlJobId?: string) {
    setSiteId(id);
    if (crawlJobId) {
      setJobId(crawlJobId);
    } else {
      router.push(`/sites/${id}`);
    }
  }

  function handleCrawlComplete() {
    if (siteId) {
      router.push(`/sites/${siteId}`);
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="max-w-7xl mx-auto">
          <Link href="/" className="text-sm text-gray-500 hover:text-gray-700">
            ← Back to Dashboard
          </Link>
        </div>
      </header>

      <main className="max-w-xl mx-auto px-6 py-12">
        <h1 className="text-2xl font-bold mb-8">Add a New Site</h1>

        {!jobId ? (
          <AddSiteForm onSuccess={handleSiteCreated} />
        ) : (
          <CrawlProgress jobId={jobId} onComplete={handleCrawlComplete} />
        )}
      </main>
    </div>
  );
}
