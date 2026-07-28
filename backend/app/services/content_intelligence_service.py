from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
import hashlib
import math
import re
from typing import Any
from urllib.parse import urlsplit
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content_intelligence import ContentInsight, InternalLinkRecommendation
from app.models.operator_action import OperatorAction
from app.models.page import Page
from app.models.search_performance import SearchAnalyticsMetric
from app.models.site import Site
from app.schemas.operator_action import OperatorActionCreate
from app.services.operator_action_service import create_action


STOPWORDS = {
    "about", "after", "again", "also", "been", "being", "between", "could", "does",
    "from", "have", "into", "more", "most", "other", "over", "same", "some", "such",
    "than", "that", "their", "there", "these", "they", "this", "those", "through",
    "under", "using", "what", "when", "where", "which", "while", "with", "your",
    "and", "for", "the", "was", "are", "you", "our", "how", "why", "not", "out",
    "can", "will", "www", "com", "https", "http", "html", "page", "site",
}


def _tokens(value: str | None) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9][a-z0-9-]{2,}", (value or "").lower())
        if token not in STOPWORDS and not token.isdigit()
    ]


def _path_from_url(value: str) -> str:
    parsed = urlsplit(value or "")
    return parsed.path or "/"


def _page_text(page: Page) -> str:
    meta = page.meta or {}
    headings = [*(meta.get("h2") or []), *(meta.get("h3") or [])]
    return " ".join(
        [
            page.path or "",
            page.title or "",
            page.h1 or "",
            page.meta_description or "",
            *[str(value) for value in headings if value],
        ]
    )[:12_000]


def _page_terms(page: Page) -> list[str]:
    return _tokens(_page_text(page))


def _topics(terms: list[str]) -> list[str]:
    counts = Counter(terms)
    top_terms = [term for term, _ in counts.most_common(6)]
    bigrams: Counter[str] = Counter()
    for left, right in zip(terms, terms[1:]):
        if left != right:
            bigrams[f"{left} {right}"] += 1
    phrases = [phrase for phrase, count in bigrams.most_common(3) if count >= 1]
    return list(dict.fromkeys([*phrases, *top_terms]))[:8]


def _entities(page: Page) -> list[str]:
    candidates = f"{page.title or ''}. {page.h1 or ''}."
    values = re.findall(r"\b[A-Z][A-Za-z0-9-]*(?:\s+[A-Z][A-Za-z0-9-]*){0,2}\b", candidates)
    return list(dict.fromkeys(value.strip() for value in values if len(value.strip()) >= 3))[:8]


def _date_from_value(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    match = re.search(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", value)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _jsonld_dates(value: Any) -> list[date]:
    dates: list[date] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in {"datepublished", "datemodified", "datecreated"}:
                parsed = _date_from_value(item)
                if parsed:
                    dates.append(parsed)
            dates.extend(_jsonld_dates(item))
    elif isinstance(value, list):
        for item in value:
            dates.extend(_jsonld_dates(item))
    return dates


def _content_date(page: Page) -> tuple[date, str]:
    dates = _jsonld_dates((page.meta or {}).get("json_ld"))
    if dates:
        return max(dates), "json_ld"
    if page.created_at:
        created = page.created_at
        return (created.date() if hasattr(created, "date") else date.today()), "first_crawl"
    return date.today(), "unknown"


def _aggregate(rows: list[Any]) -> dict[str, float]:
    impressions = sum(float(row.impressions or 0) for row in rows)
    clicks = sum(float(row.clicks or 0) for row in rows)
    position_weight = sum(float(row.position or 0) * float(row.impressions or 0) for row in rows)
    return {
        "clicks": round(clicks, 2),
        "impressions": round(impressions, 2),
        "ctr": round(clicks / impressions, 4) if impressions else 0,
        "position": round(position_weight / impressions, 2) if impressions else 0,
    }


def _pct_delta(current: float, previous: float) -> float | None:
    if previous <= 0:
        return None
    return round((current - previous) / previous, 4)


def score_content_page(
    page: Page,
    *,
    all_terms: dict[uuid.UUID, list[str]],
    query_terms_by_page: dict[uuid.UUID, list[str]],
    query_term_pages: dict[str, set[uuid.UUID]],
    current_metrics: dict[str, float],
    previous_metrics: dict[str, float],
    today: date,
) -> dict[str, Any]:
    terms = all_terms[page.id]
    term_counts = Counter(terms)
    unique_terms = sorted(term for term, count in term_counts.items() if count == 1)[:40]
    unique_ratio = len(unique_terms) / max(len(term_counts), 1)

    page_query_terms = query_terms_by_page.get(page.id, [])
    unique_query_terms = sorted(
        term for term in set(page_query_terms)
        if len(query_term_pages.get(term, set())) == 1
    )[:30]
    query_signal = min(1.0, len(unique_query_terms) / 8)
    information_gain = min(100, round(unique_ratio * 70 + query_signal * 30))

    content_date, date_basis = _content_date(page)
    age_days = max(0, (today - content_date).days)
    freshness_score = max(0, 100 - min(100, round(age_days / 3)))
    current_clicks = current_metrics["clicks"]
    previous_clicks = previous_metrics["clicks"]
    current_impressions = current_metrics["impressions"]
    previous_impressions = previous_metrics["impressions"]
    click_delta = _pct_delta(current_clicks, previous_clicks)
    impression_delta = _pct_delta(current_impressions, previous_impressions)

    decay_score = 0
    decay_reasons: list[str] = []
    if previous_impressions >= 30 and click_delta is not None and click_delta <= -0.30:
        decay_score += min(60, round(abs(click_delta) * 100))
        decay_reasons.append("clicks declined at least 30% versus the previous period")
    if previous_impressions >= 30 and impression_delta is not None and impression_delta <= -0.25:
        decay_score += min(40, round(abs(impression_delta) * 100))
        decay_reasons.append("impressions declined at least 25% versus the previous period")
    if age_days >= 365:
        decay_score += min(25, (age_days - 365) // 90 + 10)
        decay_reasons.append("content date is at least one year old")
    decay_score = min(100, decay_score)

    evidence = [
        {"signal": "information_gain_proxy", "method": "lexical_uniqueness_plus_query_terms", "unique_terms": len(unique_terms)},
        {"signal": "freshness", "date_basis": date_basis, "content_date": content_date.isoformat(), "age_days": age_days},
    ]
    if click_delta is not None or impression_delta is not None:
        evidence.append(
            {
                "signal": "search_decay",
                "current": current_metrics,
                "previous": previous_metrics,
                "click_delta": click_delta,
                "impression_delta": impression_delta,
                "reasons": decay_reasons,
            }
        )
    return {
        "content_fingerprint": page.content_hash or hashlib.sha256(_page_text(page).encode()).hexdigest(),
        "content_age_days": age_days,
        "freshness_score": freshness_score,
        "decay_score": decay_score,
        "information_gain_score": information_gain,
        "topics": _topics(terms),
        "entities": _entities(page),
        "unique_terms": unique_terms,
        "metrics": {
            "current": current_metrics,
            "previous": previous_metrics,
            "click_delta": click_delta,
            "impression_delta": impression_delta,
            "current_period_days": 28,
            "previous_period_days": 28,
            "information_gain_method": "deterministic_lexical_proxy",
        },
        "evidence": evidence,
    }


def _similarity(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0


def build_semantic_graph(pages: list[Page], scored: dict[uuid.UUID, dict[str, Any]]) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    topic_pages: dict[str, list[uuid.UUID]] = defaultdict(list)

    for page in pages:
        insight = scored[page.id]
        nodes.append({"id": f"page:{page.id}", "type": "page", "label": page.title or page.path, "path": page.path})
        for topic in insight["topics"][:6]:
            topic_id = f"topic:{topic}"
            if topic_id not in {node["id"] for node in nodes}:
                nodes.append({"id": topic_id, "type": "topic", "label": topic})
            topic_pages[topic].append(page.id)
            edges.append({"source": f"page:{page.id}", "target": topic_id, "type": "covers", "weight": 1})

    page_terms = {page.id: set(_page_terms(page)) for page in pages}
    for index, left in enumerate(pages):
        for right in pages[index + 1:]:
            shared = page_terms[left.id] & page_terms[right.id]
            score = _similarity(page_terms[left.id], page_terms[right.id])
            if len(shared) >= 2 and score >= 0.18 and len(edges) < 500:
                edges.append(
                    {
                        "source": f"page:{left.id}",
                        "target": f"page:{right.id}",
                        "type": "related",
                        "weight": round(score, 3),
                        "shared_terms": sorted(shared)[:12],
                    }
                )

    clusters = []
    for topic, page_ids in sorted(topic_pages.items(), key=lambda item: (-len(item[1]), item[0])):
        unique_ids = list(dict.fromkeys(page_ids))
        if len(unique_ids) >= 2:
            clusters.append(
                {
                    "topic": topic,
                    "pages": [str(page_id) for page_id in unique_ids[:25]],
                    "paths": [next(page.path for page in pages if page.id == page_id) for page_id in unique_ids[:25]],
                    "count": len(unique_ids),
                }
            )
    return {"nodes": nodes[:750], "edges": edges[:1_500], "topic_clusters": clusters[:50]}


def _recommendation_candidates(
    pages: list[Page],
    scored: dict[uuid.UUID, dict[str, Any]],
) -> list[dict[str, Any]]:
    page_by_path = {page.path: page for page in pages}
    candidates: list[dict[str, Any]] = []
    for target in pages:
        linked_from = (target.meta or {}).get("linked_from") or []
        if target.path == "/" or linked_from:
            continue
        target_terms = set(_page_terms(target))
        target_topics = set(scored[target.id]["topics"])
        for source in pages:
            if source.id == target.id:
                continue
            existing_links = set((source.meta or {}).get("internal_links") or [])
            if target.path in existing_links:
                continue
            shared = set(_page_terms(source)) & target_terms
            topic_overlap = set(scored[source.id]["topics"]) & target_topics
            similarity = _similarity(set(_page_terms(source)), target_terms)
            if len(shared) < 2 and not topic_overlap:
                continue
            score = min(100, 55 + len(shared) * 7 + len(topic_overlap) * 8 + round(similarity * 20))
            anchor = (target.title or next(iter(target_topics), target.path)).strip()[:255]
            candidates.append(
                {
                    "source_page_id": source.id,
                    "target_page_id": target.id,
                    "priority_score": score,
                    "confidence_score": min(100, 50 + len(shared) * 8 + round(similarity * 30)),
                    "anchor_text": anchor,
                    "reason": f"Link {source.path} to orphan page {target.path}; the pages share topical vocabulary.",
                    "evidence": [
                        {"source_path": source.path, "target_path": target.path},
                        {"shared_terms": sorted(shared)[:20], "topic_overlap": sorted(topic_overlap)},
                        {"lexical_similarity": round(similarity, 3), "target_inlinks": 0},
                    ],
                }
            )
    candidates.sort(key=lambda item: (-item["priority_score"], -item["confidence_score"], str(item["source_page_id"])))
    return candidates[:100]


async def _ensure_recommendations(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    site_id: uuid.UUID,
    candidates: list[dict[str, Any]],
    now: datetime,
) -> list[InternalLinkRecommendation]:
    active_keys: set[str] = set()
    rows: list[InternalLinkRecommendation] = []
    for candidate in candidates:
        key = f"{candidate['source_page_id']}:{candidate['target_page_id']}"
        active_keys.add(key)
        row = await db.scalar(
            select(InternalLinkRecommendation).where(
                InternalLinkRecommendation.site_id == site_id,
                InternalLinkRecommendation.recommendation_key == key,
            )
        )
        if not row:
            row = InternalLinkRecommendation(
                workspace_id=workspace_id,
                site_id=site_id,
                source_page_id=candidate["source_page_id"],
                target_page_id=candidate["target_page_id"],
                recommendation_key=key,
                first_detected_at=now,
            )
            db.add(row)
        row.status = "active"
        row.priority_score = candidate["priority_score"]
        row.confidence_score = candidate["confidence_score"]
        row.anchor_text = candidate["anchor_text"]
        row.reason = candidate["reason"]
        row.evidence = candidate["evidence"]
        row.last_detected_at = now
        row.resolved_at = None
        rows.append(row)

    existing = list(
        (
            await db.execute(
                select(InternalLinkRecommendation).where(
                    InternalLinkRecommendation.site_id == site_id,
                    InternalLinkRecommendation.status == "active",
                )
            )
        ).scalars().all()
    )
    for row in existing:
        if row.recommendation_key not in active_keys:
            row.status = "resolved"
            row.resolved_at = now
    await db.flush()
    return rows


def _insight_dict(insight: ContentInsight, page: Page) -> dict[str, Any]:
    return {
        "id": insight.id,
        "page_id": page.id,
        "path": page.path,
        "title": page.title,
        "content_age_days": insight.content_age_days,
        "freshness_score": insight.freshness_score,
        "decay_score": insight.decay_score,
        "information_gain_score": insight.information_gain_score,
        "topics": insight.topics or [],
        "entities": insight.entities or [],
        "unique_terms": insight.unique_terms or [],
        "metrics": insight.metrics or {},
        "evidence": insight.evidence or [],
        "analyzed_at": insight.analyzed_at,
    }


def _recommendation_dict(row: InternalLinkRecommendation, pages: dict[uuid.UUID, Page]) -> dict[str, Any]:
    source = pages[row.source_page_id]
    target = pages[row.target_page_id]
    return {
        "id": row.id,
        "source_page_id": row.source_page_id,
        "source_path": source.path,
        "target_page_id": row.target_page_id,
        "target_path": target.path,
        "target_title": target.title,
        "anchor_text": row.anchor_text,
        "priority_score": row.priority_score,
        "confidence_score": row.confidence_score,
        "reason": row.reason,
        "evidence": row.evidence or [],
        "status": row.status,
        "last_detected_at": row.last_detected_at,
    }


async def _create_governed_actions(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    site_id: uuid.UUID,
    site: Site,
    insights: list[ContentInsight],
    recs: list[InternalLinkRecommendation],
) -> list[uuid.UUID]:
    del site
    action_ids: list[uuid.UUID] = []
    pages = {
        page.id: page
        for page in list((await db.execute(select(Page).where(Page.site_id == site_id))).scalars().all())
    }
    candidates: list[tuple[str, dict[str, Any]]] = []
    for insight in sorted(insights, key=lambda item: -item.decay_score):
        if insight.decay_score >= 50:
            page = pages[insight.page_id]
            candidates.append(
                (
                    f"phase7:refresh:{site_id}:{page.id}:{insight.content_fingerprint}",
                    {
                        "action_type": "content_refresh_recommendation",
                        "title": f"Refresh decaying content: {page.path}",
                        "description": "Review the evidence-backed decay and information-gain signals before updating this page.",
                        "evidence": insight.evidence or [],
                        "plan": {"steps": ["Review search deltas", "Add missing information gain", "Refresh and re-measure"], "target_path": page.path},
                        "proposed_diff": {"type": "content_refresh_plan", "target_path": page.path},
                        "target_url": page.path,
                        "impact_score": min(100, insight.decay_score + 20),
                        "confidence_score": min(100, 60 + insight.information_gain_score // 4),
                    },
                )
            )
    for rec in recs[:30]:
        source = pages[rec.source_page_id]
        target = pages[rec.target_page_id]
        candidates.append(
            (
                f"phase7:link:{site_id}:{rec.recommendation_key}",
                {
                    "action_type": "internal_link_recommendation",
                    "title": f"Link {source.path} → {target.path}",
                    "description": rec.reason,
                    "evidence": rec.evidence or [],
                    "plan": {"steps": ["Review source context", "Add one contextual link", "Validate crawl and anchor"], "source_path": source.path, "target_path": target.path},
                    "proposed_diff": {"type": "internal_link", "source_path": source.path, "target_path": target.path, "anchor_text": rec.anchor_text},
                    "target_url": target.path,
                    "impact_score": rec.priority_score,
                    "confidence_score": rec.confidence_score,
                },
            )
        )
    for key, value in candidates:
        action = await create_action(
            db,
            workspace_id=workspace_id,
            user_id=None,
            data=OperatorActionCreate(
                site_id=site_id,
                action_type=value["action_type"],
                category="content",
                source="content_intelligence_pipeline",
                title=value["title"],
                description=value["description"],
                evidence=value["evidence"][:20],
                plan=value["plan"],
                impact_score=value["impact_score"],
                confidence_score=value["confidence_score"],
                effort_score=35,
                risk_score=20,
                execution_target={"adapter": "simulation", "kind": value["action_type"], "target_url": value["target_url"]},
                proposed_diff=value["proposed_diff"],
                rollback_plan={"strategy": "no_mutation", "note": "Recommendation only until a governed CMS adapter is enabled."},
                measurement_plan={"windows_days": [7, 14, 30], "metrics": ["clicks", "impressions", "internal_inlinks"]},
                validation_checklist=["Review evidence", "Confirm target context", "Re-crawl after any approved change"],
                idempotency_key=key,
            ),
        )
        action_ids.append(action.id)
    return action_ids


async def analyze_site_content(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    site_id: uuid.UUID,
    create_actions: bool = True,
) -> dict[str, Any]:
    site = await db.scalar(select(Site).where(Site.id == site_id, Site.workspace_id == workspace_id))
    if not site:
        raise ValueError("Site not found in this workspace")
    pages = list((await db.execute(select(Page).where(Page.site_id == site_id).order_by(Page.path))).scalars().all())
    today = date.today()
    period_end = today - timedelta(days=3)
    current_start = period_end - timedelta(days=27)
    previous_start = current_start - timedelta(days=28)
    rows = list(
        (
            await db.execute(
                select(SearchAnalyticsMetric).where(
                    SearchAnalyticsMetric.site_id == site_id,
                    SearchAnalyticsMetric.metric_date.between(previous_start, period_end),
                )
            )
        ).scalars().all()
    )

    all_terms = {page.id: _page_terms(page) for page in pages}
    query_terms_by_page: dict[uuid.UUID, list[str]] = defaultdict(list)
    query_term_pages: dict[str, set[uuid.UUID]] = defaultdict(set)
    grouped: dict[uuid.UUID, dict[str, list[Any]]] = defaultdict(lambda: {"current": [], "previous": []})
    for row in rows:
        path = _path_from_url(row.page_url)
        page = next((item for item in pages if item.path == path), None)
        if not page:
            continue
        bucket = "current" if current_start <= row.metric_date <= period_end else "previous"
        grouped[page.id][bucket].append(row)
        if bucket == "current":
            terms = _tokens(row.query)
            query_terms_by_page[page.id].extend(terms)
            for term in terms:
                query_term_pages[term].add(page.id)

    scored: dict[uuid.UUID, dict[str, Any]] = {}
    existing_insights = {
        row.page_id: row
        for row in list(
            (
                await db.execute(
                    select(ContentInsight).where(ContentInsight.site_id == site_id)
                )
            ).scalars().all()
        )
    }
    now = datetime.now(timezone.utc)
    insight_rows: list[ContentInsight] = []
    for page in pages:
        values = score_content_page(
            page,
            all_terms=all_terms,
            query_terms_by_page=query_terms_by_page,
            query_term_pages=query_term_pages,
            current_metrics=_aggregate(grouped[page.id]["current"]),
            previous_metrics=_aggregate(grouped[page.id]["previous"]),
            today=today,
        )
        scored[page.id] = values
        row = existing_insights.get(page.id) or ContentInsight(
            workspace_id=workspace_id,
            site_id=site_id,
            page_id=page.id,
        )
        for key, value in values.items():
            setattr(row, key, value)
        row.status = "active"
        row.analyzed_at = now
        db.add(row)
        insight_rows.append(row)

    await db.flush()
    candidates = _recommendation_candidates(pages, scored)
    rec_rows = await _ensure_recommendations(
        db,
        workspace_id=workspace_id,
        site_id=site_id,
        candidates=candidates,
        now=now,
    )
    await db.commit()
    for row in [*insight_rows, *rec_rows]:
        await db.refresh(row)

    action_ids = await _create_governed_actions(
        db,
        workspace_id=workspace_id,
        site_id=site_id,
        site=site,
        insights=insight_rows,
        recs=rec_rows,
    ) if create_actions else []
    graph = build_semantic_graph(pages, scored)
    page_map = {page.id: page for page in pages}
    decaying = sum(1 for row in insight_rows if row.decay_score >= 50)
    orphan_pages = sum(1 for page in pages if page.path != "/" and not (page.meta or {}).get("linked_from"))
    return {
        "analyzed_at": now,
        "period_end": period_end.isoformat(),
        "total_pages": len(pages),
        "decaying_pages": decaying,
        "orphan_pages": orphan_pages,
        "insights": [_insight_dict(row, page_map[row.page_id]) for row in insight_rows],
        "recommendations": [_recommendation_dict(row, page_map) for row in rec_rows],
        "semantic_graph": graph,
        "action_ids": action_ids,
    }
