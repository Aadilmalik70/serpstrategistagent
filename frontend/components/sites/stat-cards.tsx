interface StatCardsProps {
  site: {
    page_count: number;
    status: string;
    updated_at: string;
  };
}

export default function StatCards({ site }: StatCardsProps) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      <div className="bg-white rounded-lg border border-gray-200 p-5">
        <p className="text-sm text-gray-500">Pages Discovered</p>
        <p className="text-2xl font-bold mt-1">{site.page_count}</p>
      </div>
      <div className="bg-white rounded-lg border border-gray-200 p-5">
        <p className="text-sm text-gray-500">Status</p>
        <p className="text-2xl font-bold mt-1 capitalize">{site.status}</p>
      </div>
      <div className="bg-white rounded-lg border border-gray-200 p-5">
        <p className="text-sm text-gray-500">Last Updated</p>
        <p className="text-lg font-medium mt-1">
          {new Date(site.updated_at).toLocaleDateString()}
        </p>
      </div>
    </div>
  );
}
