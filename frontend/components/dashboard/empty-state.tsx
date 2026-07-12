import Link from "next/link";

export default function EmptyState() {
  return (
    <div className="operator-grid rounded-[24px] border border-[rgba(32,32,32,0.12)] bg-[#f3f0e8] px-5 py-14 text-center text-[#202020] sm:px-10 sm:py-20">
      <div className="mx-auto grid h-14 w-14 place-items-center rounded-full bg-[#202020] text-2xl text-white">
        ↗
      </div>
      <p className="mt-6 text-xs font-semibold uppercase tracking-[0.16em] text-[#646464]">
        First observation
      </p>
      <h3 className="mx-auto mt-2 max-w-lg text-3xl font-semibold tracking-[-0.045em] text-[#202020] sm:text-4xl">
        Give the operator a site to study.
      </h3>
      <p className="mx-auto mt-4 max-w-md text-sm leading-6 text-[#575757] sm:text-base">
        Add a domain to start crawling, surface technical issues and build a governed action queue.
      </p>
      <Link
        href="/sites/new"
        className="mt-7 inline-flex min-h-11 items-center justify-center rounded-full bg-[#ea2804] px-6 text-sm font-semibold text-white transition hover:bg-[#c01f00]"
      >
        Add your first site
      </Link>
    </div>
  );
}
