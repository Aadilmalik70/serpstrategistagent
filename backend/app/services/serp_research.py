"""SERP research service — fetches Google search results for keyword analysis."""
import logging
from typing import Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


async def search_serp(query: str, num_results: int = 10) -> Optional[dict]:
    """Search Google via Serper.dev API and return structured results.

    Returns None if no API key configured or request fails.
    """
    settings = get_settings()
    if not settings.serper_api_key:
        logger.info("No SERPER_API_KEY — skipping SERP research")
        return None

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://google.serper.dev/search",
                headers={
                    "X-API-KEY": settings.serper_api_key,
                    "Content-Type": "application/json",
                },
                json={"q": query, "num": num_results},
            )
            resp.raise_for_status()
            data = resp.json()

        # Extract relevant info
        organic = data.get("organic", [])
        results = []
        for r in organic[:num_results]:
            results.append({
                "position": r.get("position"),
                "title": r.get("title", ""),
                "link": r.get("link", ""),
                "snippet": r.get("snippet", ""),
            })

        people_also_ask = [
            q.get("question", "") for q in data.get("peopleAlsoAsk", [])
        ]

        related_searches = [
            s.get("query", "") for s in data.get("relatedSearches", [])
        ]

        return {
            "query": query,
            "organic_results": results,
            "people_also_ask": people_also_ask,
            "related_searches": related_searches,
            "total_results": len(results),
        }

    except Exception as e:
        logger.warning(f"SERP research failed for '{query}': {e}")
        return None


async def analyze_competitors(keyword: str) -> dict:
    """Analyze top-ranking pages for a keyword to inform content generation."""
    serp = await search_serp(keyword)
    if not serp:
        return {"keyword": keyword, "available": False}

    titles = [r["title"] for r in serp["organic_results"]]
    avg_title_len = sum(len(t) for t in titles) / max(len(titles), 1)

    return {
        "keyword": keyword,
        "available": True,
        "top_titles": titles[:5],
        "avg_title_length": round(avg_title_len),
        "people_also_ask": serp["people_also_ask"][:5],
        "related_searches": serp["related_searches"][:5],
        "top_snippets": [r["snippet"] for r in serp["organic_results"][:3]],
    }
