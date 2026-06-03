import Link from "next/link";

export default function EmptyState() {
  return (
    <div className="text-center py-16">
      <div className="text-5xl mb-4">🌐</div>
      <h3 className="text-lg font-semibold text-gray-900 mb-2">
        No sites yet
      </h3>
      <p className="text-gray-600 mb-6 max-w-sm mx-auto">
        Add your first site to get started. The agent will crawl it and discover
        optimization opportunities.
      </p>
      <Link
        href="/sites/new"
        className="inline-flex px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 text-sm font-medium"
      >
        Add Your First Site
      </Link>
    </div>
  );
}
