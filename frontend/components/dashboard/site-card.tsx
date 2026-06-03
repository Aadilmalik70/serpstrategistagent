import Link from "next/link";

interface SiteCardProps {
  site: {
    id: string;
    domain: string;
    name: string;
    status: string;
  };
}

export default function SiteCard({ site }: SiteCardProps) {
  const statusColor =
    site.status === "active"
      ? "bg-green-100 text-green-800"
      : site.status === "crawling"
        ? "bg-yellow-100 text-yellow-800"
        : "bg-gray-100 text-gray-800";

  return (
    <Link href={`/sites/${site.id}`}>
      <div className="bg-white rounded-lg border border-gray-200 p-5 hover:shadow-md transition-shadow cursor-pointer">
        <div className="flex items-start justify-between">
          <div>
            <h3 className="font-semibold text-gray-900">{site.name}</h3>
            <p className="text-sm text-gray-500 mt-1">{site.domain}</p>
          </div>
          <span
            className={`text-xs px-2 py-1 rounded-full font-medium ${statusColor}`}
          >
            {site.status}
          </span>
        </div>
      </div>
    </Link>
  );
}
