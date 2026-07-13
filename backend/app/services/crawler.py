"""Compatibility entry point for the first-party crawler.

The original basic crawler and LibreCrawl dependency have been replaced by the
bounded first-party crawler. Existing imports may continue using ``run_crawl``.
"""

from app.services.first_party_crawler import (
    CrawlError,
    PageHtmlParser,
    run_first_party_crawl,
)

run_crawl = run_first_party_crawl

__all__ = ["CrawlError", "PageHtmlParser", "run_crawl", "run_first_party_crawl"]
