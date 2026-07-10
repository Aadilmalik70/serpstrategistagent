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
  const active = site.status === "active";
  const crawling = site.status === "crawling";
  const statusClass = active
    ? "bg-[#2b9a66] text-white"
    : crawling
      ? "bg-[#f3f0e8] text-[#202020]"
      : "border border-[rgba(32,32,32,0.12)] bg-white text-[#646464]";

  return (
    <Link
      href={`/sites/${site.id}`}
      className="group block rounded-[18px] border border-[rgba(32,32,32,0.12)] bg-white p-5 text-[#202020] transition duration-200 hover:-translate-y-0.5 hover:border-[rgba(32,32,32,0.28)] sm:p-6"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="grid h-11 w-11 place-items-center rounded-2xl bg-[#202020] text-sm font-bold text-white">
            {site.name.slice(0, 2).toUpperCase()}
          </div>
          <h3 className="mt-5 truncate text-lg font-semibold tracking-[-0.025em] text-[#202020]">
            {site.name}
          </h3>
          <p className="mt-1 truncate font-mono text-xs text-[#646464]">{site.domain}</p>
        </div>
        <span className={`shrink-0 rounded-full px-3 py-1 text-xs font-semibold capitalize ${statusClass}`}>
          {site.status}
        </span>
      </div>
      <div className="mt-7 flex items-center justify-between border-t border-[rgba(32,32,32,0.1)] pt-4">
        <span className="text-sm text-[#646464]">Open operator view</span>
        <span className="grid h-9 w-9 place-items-center rounded-full border border-[rgba(32,32,32,0.14)] text-[#202020] transition group-hover:bg-[#ea2804] group-hover:text-white">
          →
        </span>
      </div>
    </Link>
  );
}
