from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.citation_intelligence import CitationGap, CitationPromptSet, CitationResult, CitationScan
from app.models.site import Site
from app.schemas.citation_intelligence import CitationPromptSetCreate, CitationResultIngest
from app.schemas.operator_action import OperatorActionCreate
from app.services.operator_action_service import create_action

SUPPORTED_PROVIDERS = {"manual", "openai", "gemini", "perplexity"}
PROVIDER_NOTES = [
    "Results are ingested from official/provider APIs or the manual test adapter; browser scraping is not supported.",
    "Provider availability, citations, and answer formats vary. The dashboard stores provider identity and evidence.",
    "Citation-gap actions are simulation-only until a governed content execution adapter is enabled.",
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash(value: str) -> str:
    return hashlib.sha256(value.strip().lower().encode()).hexdigest()


def _normalize_url(value: str) -> str | None:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", parsed.query, ""))[:2048]


def analyze_answer(
    *,
    answer: str,
    brand_terms: list[str],
    competitor_terms: list[str],
    cited_urls: list[str],
) -> dict[str, Any]:
    normalized = answer.casefold()
    brand_matches = [term for term in brand_terms if term.casefold() in normalized]
    competitors = [term for term in competitor_terms if term.casefold() in normalized]
    urls = list(dict.fromkeys(item for item in (_normalize_url(url) for url in cited_urls) if item))
    evidence: list[dict[str, Any]] = [
        {"signal": "brand_mention", "matched": bool(brand_matches), "terms": brand_matches},
        {"signal": "citations", "count": len(urls), "urls": urls[:20]},
        {"signal": "competitor_mentions", "terms": competitors},
    ]
    if competitors and not brand_matches:
        gap_type = "competitor_gap"
    elif not brand_matches:
        gap_type = "brand_mention_gap"
    elif not urls:
        gap_type = "citation_gap"
    else:
        gap_type = None
    return {
        "brand_mentioned": bool(brand_matches),
        "cited_urls": urls,
        "competitor_mentions": competitors,
        "gap_type": gap_type,
        "evidence": evidence,
    }


def aggregate_scan_results(results: list[dict[str, Any]], competitor_terms: list[str]) -> dict[str, Any]:
    total = len(results)
    mentioned = sum(1 for item in results if item.get("brand_mentioned"))
    cited = sum(1 for item in results if item.get("cited_urls"))
    competitor_metrics = {
        term: sum(1 for item in results if term in (item.get("competitor_mentions") or []))
        for term in competitor_terms
    }
    mention_rate = round(mentioned / total, 4) if total else 0.0
    citation_rate = round(cited / total, 4) if total else 0.0
    return {
        "visibility_score": min(100, round(mention_rate * 70 + citation_rate * 30)),
        "mention_rate": mention_rate,
        "citation_rate": citation_rate,
        "competitor_metrics": competitor_metrics,
    }


def gap_priority(gap_type: str, *, competitor: bool = False) -> tuple[int, int]:
    if gap_type == "brand_mention_gap":
        return 85, 82
    if gap_type == "citation_gap":
        return 70, 78
    if competitor:
        return 76, 70
    return 50, 60


async def _require_site(db: AsyncSession, workspace_id: uuid.UUID, site_id: uuid.UUID) -> Site:
    site = await db.scalar(select(Site).where(Site.id == site_id, Site.workspace_id == workspace_id))
    if not site:
        raise ValueError("Site not found in this workspace")
    return site


def prompt_set_to_dict(item: CitationPromptSet) -> dict[str, Any]:
    return {
        "id": item.id,
        "site_id": item.site_id,
        "name": item.name,
        "brand_terms": item.brand_terms or [],
        "competitor_terms": item.competitor_terms or [],
        "prompts": item.prompts or [],
        "providers": item.providers or [],
        "schedule_interval_hours": item.schedule_interval_hours,
        "status": item.status,
        "last_run_at": item.last_run_at,
        "next_run_at": item.next_run_at,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def scan_to_dict(item: CitationScan) -> dict[str, Any]:
    return {
        "id": item.id,
        "prompt_set_id": item.prompt_set_id,
        "status": item.status,
        "providers": item.providers or [],
        "prompt_count": item.prompt_count,
        "result_count": item.result_count,
        "visibility_score": item.visibility_score,
        "mention_rate": item.mention_rate,
        "citation_rate": item.citation_rate,
        "competitor_metrics": item.competitor_metrics or {},
        "error_message": item.error_message,
        "created_at": item.created_at,
        "completed_at": item.completed_at,
    }


def result_to_dict(item: CitationResult) -> dict[str, Any]:
    return {
        "id": item.id,
        "provider": item.provider,
        "prompt": item.prompt,
        "answer_excerpt": item.answer_excerpt,
        "brand_mentioned": item.brand_mentioned,
        "cited_urls": item.cited_urls or [],
        "competitor_mentions": item.competitor_mentions or [],
        "evidence": item.evidence or [],
        "captured_at": item.captured_at,
    }


def gap_to_dict(item: CitationGap) -> dict[str, Any]:
    return {
        "id": item.id,
        "gap_type": item.gap_type,
        "status": item.status,
        "prompt": item.prompt,
        "competitor": item.competitor,
        "priority_score": item.priority_score,
        "confidence_score": item.confidence_score,
        "evidence": item.evidence or [],
        "action_id": item.action_id,
        "last_detected_at": item.last_detected_at,
    }


async def create_prompt_set(
    db: AsyncSession, *, workspace_id: uuid.UUID, site_id: uuid.UUID, data: CitationPromptSetCreate
) -> CitationPromptSet:
    await _require_site(db, workspace_id, site_id)
    providers = [provider.strip().lower() for provider in data.providers]
    unsupported = sorted(set(providers) - SUPPORTED_PROVIDERS)
    if unsupported:
        raise ValueError(f"Unsupported citation providers: {', '.join(unsupported)}")
    item = CitationPromptSet(
        workspace_id=workspace_id,
        site_id=site_id,
        name=data.name,
        brand_terms=data.brand_terms,
        competitor_terms=data.competitor_terms,
        prompts=data.prompts,
        providers=providers,
        schedule_interval_hours=data.schedule_interval_hours,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


async def list_prompt_sets(db: AsyncSession, *, workspace_id: uuid.UUID, site_id: uuid.UUID) -> list[CitationPromptSet]:
    await _require_site(db, workspace_id, site_id)
    return list((await db.execute(select(CitationPromptSet).where(CitationPromptSet.site_id == site_id).order_by(CitationPromptSet.updated_at.desc()))).scalars().all())


async def create_scan(db: AsyncSession, *, workspace_id: uuid.UUID, site_id: uuid.UUID, prompt_set_id: uuid.UUID) -> CitationScan:
    prompt_set = await db.scalar(
        select(CitationPromptSet).where(
            CitationPromptSet.id == prompt_set_id,
            CitationPromptSet.site_id == site_id,
            CitationPromptSet.workspace_id == workspace_id,
            CitationPromptSet.status == "active",
        )
    )
    if not prompt_set:
        raise ValueError("Citation prompt set not found in this workspace")
    scan = CitationScan(
        workspace_id=workspace_id,
        site_id=site_id,
        prompt_set_id=prompt_set.id,
        status="queued",
        providers=prompt_set.providers or ["manual"],
        prompt_count=len(prompt_set.prompts or []),
    )
    db.add(scan)
    await db.commit()
    await db.refresh(scan)
    return scan


async def ingest_result(
    db: AsyncSession, *, workspace_id: uuid.UUID, site_id: uuid.UUID, scan_id: uuid.UUID, data: CitationResultIngest
) -> CitationResult:
    scan = await db.scalar(
        select(CitationScan).where(CitationScan.id == scan_id, CitationScan.site_id == site_id, CitationScan.workspace_id == workspace_id)
    )
    if not scan:
        raise ValueError("Citation scan not found in this workspace")
    prompt_set = await db.get(CitationPromptSet, scan.prompt_set_id)
    if not prompt_set:
        raise ValueError("Citation prompt set is unavailable")
    provider = data.provider.strip().lower()
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(f"Unsupported citation provider: {provider}")
    if data.prompt.strip() not in (prompt_set.prompts or []):
        raise ValueError("Prompt is not part of the selected prompt set")
    analysis = analyze_answer(
        answer=data.answer,
        brand_terms=prompt_set.brand_terms or [],
        competitor_terms=prompt_set.competitor_terms or [],
        cited_urls=data.cited_urls,
    )
    prompt_hash = _hash(data.prompt)
    result = await db.scalar(select(CitationResult).where(CitationResult.scan_id == scan.id, CitationResult.provider == provider, CitationResult.prompt_hash == prompt_hash))
    if not result:
        result = CitationResult(
            workspace_id=workspace_id,
            site_id=site_id,
            scan_id=scan.id,
            provider=provider,
            prompt_hash=prompt_hash,
            prompt=data.prompt.strip(),
        )
        db.add(result)
    result.answer_excerpt=data.answer.strip()[:2000]
    result.brand_mentioned=analysis["brand_mentioned"]
    result.cited_urls=analysis["cited_urls"]
    result.competitor_mentions=analysis["competitor_mentions"]
    result.evidence=analysis["evidence"]
    scan.status="running"
    scan.started_at=scan.started_at or _now()
    await db.commit()
    await db.refresh(result)
    return result


async def finalize_scan(db: AsyncSession, *, workspace_id: uuid.UUID, site_id: uuid.UUID, scan_id: uuid.UUID, create_actions: bool = True) -> CitationScan:
    scan = await db.scalar(select(CitationScan).where(CitationScan.id == scan_id, CitationScan.site_id == site_id, CitationScan.workspace_id == workspace_id))
    if not scan:
        raise ValueError("Citation scan not found in this workspace")
    prompt_set = await db.get(CitationPromptSet, scan.prompt_set_id)
    results = list((await db.execute(select(CitationResult).where(CitationResult.scan_id == scan.id))).scalars().all())
    summary = aggregate_scan_results(
        [{"brand_mentioned": item.brand_mentioned, "cited_urls": item.cited_urls, "competitor_mentions": item.competitor_mentions} for item in results],
        prompt_set.competitor_terms or [],
    )
    scan.status="completed"
    scan.result_count=len(results)
    scan.visibility_score=summary["visibility_score"]
    scan.mention_rate=summary["mention_rate"]
    scan.citation_rate=summary["citation_rate"]
    scan.competitor_metrics=summary["competitor_metrics"]
    scan.completed_at=_now()
    prompt_set.last_run_at=scan.completed_at
    if prompt_set.schedule_interval_hours:
        from datetime import timedelta
        prompt_set.next_run_at=scan.completed_at + timedelta(hours=prompt_set.schedule_interval_hours)

    active_keys: set[str] = set()
    for result in results:
        brand_present = bool(result.brand_mentioned)
        competitors = result.competitor_mentions or []
        gap_type = (
            "competitor_gap" if competitors and not brand_present
            else "brand_mention_gap" if not brand_present
            else "citation_gap" if not result.cited_urls
            else None
        )
        if not gap_type:
            continue
        competitor = (competitors or [None])[0]
        gap_key = _hash(f"{gap_type}|{result.prompt_hash}|{competitor or ''}")[:128]
        active_keys.add(gap_key)
        priority, confidence = gap_priority(gap_type, competitor=bool(competitor))
        gap = await db.scalar(select(CitationGap).where(CitationGap.site_id == site_id, CitationGap.gap_key == gap_key))
        if not gap:
            gap = CitationGap(workspace_id=workspace_id, site_id=site_id, scan_id=scan.id, gap_key=gap_key, gap_type=gap_type, prompt=result.prompt)
            db.add(gap)
            await db.flush()
        gap.scan_id=scan.id
        gap.status="active"
        gap.competitor=competitor
        gap.priority_score=priority
        gap.confidence_score=confidence
        gap.evidence=result.evidence or []
        gap.last_detected_at=_now()
        gap.resolved_at=None
        if create_actions and not gap.action_id:
            action = await create_action(
                db,
                workspace_id=workspace_id,
                user_id=None,
                data=OperatorActionCreate(
                    site_id=site_id,
                    action_type="citation_gap",
                    category="content",
                    source="citation_intelligence",
                    title=f"Close AI citation gap for: {result.prompt[:100]}",
                    description="Improve the evidence and source coverage used for this prompt, then re-run the same provider scan.",
                    evidence=[{"scan_id": str(scan.id), "gap_type": gap_type, "prompt": result.prompt, "provider": result.provider, "signals": result.evidence or []}],
                    plan={"steps": ["Review the prompt-level answer and cited sources", "Strengthen first-party evidence or content coverage", "Re-run the same prompt set and compare visibility"]},
                    impact_score=priority,
                    confidence_score=confidence,
                    effort_score=55,
                    risk_score=20,
                    execution_target={"adapter": "simulation", "reason": "Citation intelligence has no CMS mutation adapter enabled"},
                    rollback_plan={"strategy": "No mutation performed; dismiss or replace the recommendation"},
                    measurement_plan={"metric": "AI mention and citation rate", "window": "next_completed_scan"},
                    validation_checklist=["Provider result is captured", "Brand mention/citation evidence is visible", "No automatic content publication occurs"],
                    idempotency_key=f"citation-gap:{gap_key}",
                ),
            )
            gap.action_id=action.id
    if active_keys:
        old = list((await db.execute(select(CitationGap).where(CitationGap.site_id == site_id, CitationGap.status == "active"))).scalars().all())
        for gap in old:
            if gap.gap_key not in active_keys:
                gap.status="resolved"
                gap.resolved_at=_now()
    await db.commit()
    await db.refresh(scan)
    return scan


async def get_dashboard(db: AsyncSession, *, workspace_id: uuid.UUID, site_id: uuid.UUID) -> dict[str, Any]:
    await _require_site(db, workspace_id, site_id)
    prompt_sets = list((await db.execute(select(CitationPromptSet).where(CitationPromptSet.site_id == site_id).order_by(CitationPromptSet.updated_at.desc()))).scalars().all())
    latest = await db.scalar(select(CitationScan).where(CitationScan.site_id == site_id).order_by(CitationScan.created_at.desc()).limit(1))
    results = []
    gaps = []
    if latest:
        results = list((await db.execute(select(CitationResult).where(CitationResult.scan_id == latest.id).order_by(CitationResult.captured_at.desc()))).scalars().all())
        gaps = list((await db.execute(select(CitationGap).where(CitationGap.site_id == site_id, CitationGap.status == "active").order_by(CitationGap.priority_score.desc()))).scalars().all())
    return {
        "prompt_sets": [prompt_set_to_dict(item) for item in prompt_sets],
        "latest_scan": scan_to_dict(latest) if latest else None,
        "results": [result_to_dict(item) for item in results],
        "gaps": [gap_to_dict(item) for item in gaps],
        "provider_notes": PROVIDER_NOTES,
    }
