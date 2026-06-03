"""LLM-powered SEO content analysis using Groq (Llama) or Google Gemini."""
import json
import logging
from dataclasses import dataclass

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class LLMInsight:
    category: str  # technical, content, opportunity
    severity: str  # critical, high, medium, low
    title: str
    description: str
    recommendation: str


ANALYSIS_PROMPT = """You are an expert SEO analyst. Analyze this page's metadata and produce actionable SEO findings.

## Page Data
- URL Path: {path}
- Full Domain: {domain}
- Title: {title}
- Meta Description: {meta_description}
- H1: {h1}
- Word Count: {word_count}
- Status Code: {status_code}
- Response Time: {response_time_ms}ms

## Site Context
- Domain: {domain}
- Total Pages: {total_pages}
- Site Name: {site_name}

## Your Task
Analyze this page and return a JSON array of findings. Focus on:
1. **Content quality** — Is the title compelling? Does it target a clear keyword? Is the meta description a good CTA?
2. **Keyword targeting** — What keyword is this page likely targeting? Is it well-optimized for that keyword?
3. **Opportunities** — What related topics, internal linking, or content improvements would help this page rank?

Only return findings that are specific and actionable. Do NOT repeat generic advice like "add a title" if the title exists.

Return ONLY a JSON array (no markdown, no explanation):
[
  {{
    "category": "content|technical|opportunity",
    "severity": "critical|high|medium|low",
    "title": "Short issue title",
    "description": "Specific explanation of the issue for this page",
    "recommendation": "Exact action to take"
  }}
]

If the page looks well-optimized and you have no specific findings, return an empty array: []
"""


def _get_llm():
    """Get the best available LLM (Groq preferred, Gemini fallback)."""
    settings = get_settings()

    if settings.groq_api_key:
        from langchain_groq import ChatGroq
        return ChatGroq(
            model="llama-3.3-70b-versatile",
            api_key=settings.groq_api_key,
            temperature=0.1,
            max_retries=1,
            timeout=30,
        )

    if settings.google_api_key:
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model="gemini-2.0-flash",
            google_api_key=settings.google_api_key,
            temperature=0.1,
            max_retries=0,
            timeout=30,
        )

    return None


async def analyze_page_with_llm(
    page_data: dict,
    site_context: dict,
) -> list[LLMInsight]:
    """Analyze a single page using available LLM and return insights."""
    llm = _get_llm()
    if not llm:
        return []

    try:

        prompt = ANALYSIS_PROMPT.format(
            path=page_data.get("path", "/"),
            domain=site_context.get("domain", ""),
            title=page_data.get("title", "None"),
            meta_description=page_data.get("meta_description", "None"),
            h1=page_data.get("h1", "None"),
            word_count=page_data.get("word_count", 0),
            status_code=page_data.get("status_code", 0),
            response_time_ms=page_data.get("response_time_ms", 0),
            total_pages=site_context.get("total_pages", 0),
            site_name=site_context.get("site_name", ""),
        )

        response = await llm.ainvoke(prompt)
        content = response.content.strip()

        # Parse JSON from response (handle markdown code blocks)
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        findings = json.loads(content)

        insights = []
        for f in findings:
            if all(k in f for k in ("category", "severity", "title", "description", "recommendation")):
                if f["category"] in ("technical", "content", "opportunity") and \
                   f["severity"] in ("critical", "high", "medium", "low"):
                    insights.append(LLMInsight(
                        category=f["category"],
                        severity=f["severity"],
                        title=f["title"],
                        description=f["description"],
                        recommendation=f["recommendation"],
                    ))

        return insights

    except Exception as e:
        logger.warning(f"LLM analysis failed for {page_data.get('path', '?')}: {e}")
        return []


async def analyze_site_with_llm(
    pages: list[dict],
    site_context: dict,
    max_pages: int = 10,
) -> list[tuple[dict, list[LLMInsight]]]:
    """Analyze top pages with LLM. Returns list of (page_data, insights) tuples."""
    if not _get_llm():
        logger.info("No LLM API key set (GROQ_API_KEY or GOOGLE_API_KEY) — skipping LLM analysis")
        return []

    # Prioritize important pages: homepage first, then by word count (skip 404s)
    analyzable = [p for p in pages if p.get("status_code") == 200]
    analyzable.sort(key=lambda p: (0 if p["path"] == "/" else 1, -(p.get("word_count") or 0)))
    analyzable = analyzable[:max_pages]

    results = []
    consecutive_failures = 0
    for page_data in analyzable:
        insights = await analyze_page_with_llm(page_data, site_context)
        if insights:
            results.append((page_data, insights))
            consecutive_failures = 0
        else:
            consecutive_failures += 1
            # If first 2 pages all fail, likely quota issue — bail early
            if consecutive_failures >= 2 and not results:
                logger.warning("LLM analysis failing consecutively — aborting (possible quota issue)")
                break

    return results
