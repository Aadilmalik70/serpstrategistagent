"""Detect website technology stack from crawled page data."""
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.page import Page

logger = logging.getLogger(__name__)


# Signals that indicate specific frameworks/CMS
TECH_SIGNALS = {
    "nextjs": [
        "/_next/",
        "__next",
        "next/image",
        "__NEXT_DATA__",
    ],
    "nuxt": [
        "/_nuxt/",
        "__nuxt",
    ],
    "gatsby": [
        "/static/",
        "gatsby",
    ],
    "react": [
        "react",
        "__REACT",
    ],
    "wordpress": [
        "/wp-content/",
        "/wp-includes/",
        "/wp-json/",
        "wp-block",
    ],
    "shopify": [
        "cdn.shopify.com",
        "shopify",
    ],
    "wix": [
        "wix.com",
        "_wix",
    ],
}

CMS_SIGNALS = {
    "sanity": [
        "cdn.sanity.io",
        "sanity",
        "sanity.io",
    ],
    "wordpress": [
        "/wp-json/",
        "/wp-admin/",
        "/wp-content/",
        "/xmlrpc.php",
    ],
    "ghost": [
        "/ghost/api/",
        "ghost",
    ],
    "strapi": [
        "/api/",
        "strapi",
    ],
}


async def detect_tech_stack(db: AsyncSession, site_id) -> dict:
    """Detect technology stack from crawled pages.

    Returns:
        {
            "tech_stack": "nextjs" | "wordpress" | "react" | ...,
            "cms": "wordpress" | "ghost" | "none",
            "signals": ["/_next/ found in 5 pages", ...]
        }
    """
    result = await db.execute(
        select(Page.path, Page.title, Page.h1)
        .where(Page.site_id == site_id)
    )
    pages = result.all()

    # Collect all paths for signal matching
    all_paths = [p.path for p in pages]
    path_text = " ".join(all_paths).lower()

    # Detect framework
    tech_scores = {}
    signals_found = []

    for tech, signals in TECH_SIGNALS.items():
        score = 0
        for signal in signals:
            matches = sum(1 for p in all_paths if signal.lower() in p.lower())
            if matches > 0:
                score += matches
                signals_found.append(f"{signal} found in {matches} pages")
        if score > 0:
            tech_scores[tech] = score

    # Detect CMS
    cms_scores = {}
    for cms, signals in CMS_SIGNALS.items():
        score = 0
        for signal in signals:
            matches = sum(1 for p in all_paths if signal.lower() in p.lower())
            if matches > 0:
                score += matches
        if score > 0:
            cms_scores[cms] = score

    # Pick the highest scoring
    tech_stack = max(tech_scores, key=tech_scores.get) if tech_scores else "unknown"
    cms = max(cms_scores, key=cms_scores.get) if cms_scores else "none"

    # If WordPress is both tech and CMS, that's a pure WP site
    if tech_stack == "wordpress" and cms == "wordpress":
        tech_stack = "wordpress"

    # Special case: Next.js site with WordPress CMS for blog
    if tech_stack == "nextjs" and cms == "wordpress":
        pass  # Hybrid — both are correct

    logger.info(f"Detected tech for site {site_id}: stack={tech_stack}, cms={cms}")

    return {
        "tech_stack": tech_stack,
        "cms": cms,
        "signals": signals_found[:10],  # Limit to top 10 signals
    }
