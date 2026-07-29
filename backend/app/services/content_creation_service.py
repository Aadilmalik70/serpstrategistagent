from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Mapping
from urllib.parse import quote
import uuid

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.citation_intelligence import CitationGap
from app.models.content_creation import ContentBrief, ContentDraft, ContentDraftVersion, ContentOpportunity, ContentQualityCheck
from app.models.content_intelligence import ContentInsight, InternalLinkRecommendation
from app.models.page import Page
from app.models.search_performance import SearchOpportunity
from app.models.site import Site
from app.schemas.content_creation import ContentBriefCreate, ContentDraftUpdate
from app.schemas.operator_action import OperatorActionCreate
from app.services.ai_gateway import AIGatewayError, request_ai
from app.services.operator_action_service import create_action


class ContentCreationError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _next_draft_version(
    current_version: int | None,
    *,
    is_new_version: bool,
    has_persisted_id: bool,
) -> int:
    """Return a valid draft version even for legacy rows with a NULL version."""
    current = current_version or 0
    return max(1, current + 1 if is_new_version and has_persisted_id else current)


async def _site(db: AsyncSession, workspace_id: uuid.UUID, site_id: uuid.UUID) -> Site:
    site = await db.scalar(select(Site).where(Site.id == site_id, Site.workspace_id == workspace_id))
    if not site:
        raise ContentCreationError("Site not found in this workspace", 404)
    return site


def _brief_dict(item: ContentBrief) -> dict[str, Any]:
    return {
        "id": item.id, "site_id": item.site_id, "opportunity_id": item.opportunity_id, "page_id": item.page_id,
        "status": item.status, "title": item.title, "target_query": item.target_query,
        "search_intent": item.search_intent, "page_type": item.page_type, "audience": item.audience,
        "business_goal": item.business_goal, "outline": item.outline or [], "required_topics": item.required_topics or [],
        "required_entities": item.required_entities or [], "internal_link_targets": item.internal_link_targets or [],
        "faq_questions": item.faq_questions or [], "schema_recommendations": item.schema_recommendations or [],
        "information_gain": item.information_gain or [], "evidence": item.evidence or [], "scores": item.scores or {},
        "created_at": item.created_at, "updated_at": item.updated_at,
    }


def _draft_dict(item: ContentDraft) -> dict[str, Any]:
    return {
        "id": item.id, "site_id": item.site_id, "brief_id": item.brief_id, "action_id": item.action_id,
        "status": item.status, "title": item.title, "slug": item.slug, "meta_title": item.meta_title,
        "meta_description": item.meta_description, "body_markdown": item.body_markdown,
        "generation_mode": item.generation_mode, "word_count": item.word_count, "version": item.version,
        "quality_summary": item.quality_summary or {}, "created_at": item.created_at, "updated_at": item.updated_at,
    }


def _opportunity_dict(item: ContentOpportunity) -> dict[str, Any]:
    return {
        "id": item.id, "site_id": item.site_id, "page_id": item.page_id, "opportunity_type": item.opportunity_type,
        "status": item.status, "title": item.title, "summary": item.summary, "target_query": item.target_query,
        "target_path": item.target_path, "priority_score": item.priority_score, "confidence_score": item.confidence_score,
        "effort_score": item.effort_score, "evidence": item.evidence or [], "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _opportunity_payload_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Build an API payload from explicitly selected scalar columns."""
    return {
        "id": row["id"], "site_id": row["site_id"], "page_id": row["page_id"], "opportunity_type": row["opportunity_type"],
        "status": row["status"], "title": row["title"], "summary": row["summary"], "target_query": row["target_query"],
        "target_path": row["target_path"], "priority_score": row["priority_score"], "confidence_score": row["confidence_score"],
        "effort_score": row["effort_score"], "evidence": row["evidence"] or [], "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


async def _opportunity_payload(
    db: AsyncSession,
    rows: list[ContentOpportunity],
) -> list[dict[str, Any]]:
    """Reload response columns explicitly after sync_opportunities flushes.

    SQLAlchemy may expire server-managed columns such as ``updated_at`` during
    flush. Reading those attributes from async ORM instances can trigger an
    implicit IO operation and raise MissingGreenlet. A scalar-column query
    keeps response serialization fully loaded and IO-explicit.
    """
    opportunity_ids = [row.id for row in rows]
    if not opportunity_ids:
        return []

    result = await db.execute(
        select(
            ContentOpportunity.id,
            ContentOpportunity.site_id,
            ContentOpportunity.page_id,
            ContentOpportunity.opportunity_type,
            ContentOpportunity.status,
            ContentOpportunity.title,
            ContentOpportunity.summary,
            ContentOpportunity.target_query,
            ContentOpportunity.target_path,
            ContentOpportunity.priority_score,
            ContentOpportunity.confidence_score,
            ContentOpportunity.effort_score,
            ContentOpportunity.evidence,
            ContentOpportunity.created_at,
            ContentOpportunity.updated_at,
        ).where(ContentOpportunity.id.in_(opportunity_ids))
    )
    payload_by_id = {
        item["id"]: _opportunity_payload_from_row(item)
        for item in result.mappings().all()
    }
    return [payload_by_id[item_id] for item_id in opportunity_ids if item_id in payload_by_id]


async def sync_opportunities(db: AsyncSession, *, workspace_id: uuid.UUID, site_id: uuid.UUID) -> list[ContentOpportunity]:
    await _site(db, workspace_id, site_id)
    candidates: list[dict[str, Any]] = []
    insights = list((await db.execute(select(ContentInsight, Page).join(Page, Page.id == ContentInsight.page_id).where(ContentInsight.site_id == site_id).order_by(desc(ContentInsight.decay_score)))).all())
    for insight, page in insights:
        if insight.decay_score >= 25:
            candidates.append({
                "key": f"refresh:{page.id}", "type": "refresh", "page_id": page.id,
                "title": f"Refresh {page.title or page.path}",
                "summary": "Search decay and freshness signals indicate that this page should be refreshed before it loses more visibility.",
                "query": None, "path": page.path,
                "priority": min(100, insight.decay_score + 20), "confidence": min(100, 60 + insight.decay_score // 3), "effort": 45,
                "evidence": [{"signal": "content_intelligence", "path": page.path, "decay_score": insight.decay_score, "freshness_score": insight.freshness_score, "information_gain_score": insight.information_gain_score}],
            })
    search_rows = list((await db.execute(select(SearchOpportunity).where(SearchOpportunity.site_id == site_id, SearchOpportunity.status == "active").order_by(desc(SearchOpportunity.priority_score)).limit(50))).scalars().all())
    for row in search_rows:
        candidates.append({
            "key": f"search:{row.opportunity_key}", "type": "new_page", "page_id": None,
            "title": row.title or f"Create content for {row.query or 'search opportunity'}",
            "summary": "A Search Console opportunity can be converted into a focused page brief with measurable intent and evidence.",
            "query": row.query, "path": row.page_url, "priority": row.priority_score, "confidence": row.confidence_score, "effort": 55,
            "evidence": [{"signal": "search_opportunity", "query": row.query, "page_url": row.page_url, "metrics": row.metrics or {}, "source_evidence": row.evidence or []}],
        })
    gaps = list((await db.execute(select(CitationGap).where(CitationGap.site_id == site_id, CitationGap.status == "active").order_by(desc(CitationGap.priority_score)).limit(25))).scalars().all())
    for gap in gaps:
        candidates.append({
            "key": f"citation:{gap.gap_key}", "type": "authority", "page_id": None,
            "title": f"Build an answer for: {gap.prompt[:110]}",
            "summary": "An AI citation gap suggests a structured, quotable answer could improve answer coverage.",
            "query": gap.prompt, "path": None, "priority": gap.priority_score, "confidence": gap.confidence_score, "effort": 60,
            "evidence": [{"signal": "citation_gap", "prompt": gap.prompt, "competitor": gap.competitor, "gap_type": gap.gap_type, "source_evidence": gap.evidence or []}],
        })
    candidates.sort(key=lambda value: (-value["priority"], -value["confidence"], value["key"]))
    active_keys = {item["key"] for item in candidates[:100]}
    rows: list[ContentOpportunity] = []
    for candidate in candidates[:100]:
        row = await db.scalar(select(ContentOpportunity).where(ContentOpportunity.site_id == site_id, ContentOpportunity.opportunity_key == candidate["key"]))
        if not row:
            row = ContentOpportunity(workspace_id=workspace_id, site_id=site_id, opportunity_key=candidate["key"])
            db.add(row)
        row.page_id = candidate["page_id"]
        row.opportunity_type = candidate["type"]
        row.status = "open" if candidate["key"] in active_keys else "stale"
        row.title = candidate["title"]
        row.summary = candidate["summary"]
        row.target_query = candidate["query"]
        row.target_path = candidate["path"]
        row.priority_score = candidate["priority"]
        row.confidence_score = candidate["confidence"]
        row.effort_score = candidate["effort"]
        row.evidence = candidate["evidence"]
        rows.append(row)
    await db.flush()
    return rows


def _terms(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in result:
            result.append(text)
    return result[:20]


def _serialize_internal_link_targets(
    rows: list[tuple[InternalLinkRecommendation, Page]],
) -> list[dict[str, str]]:
    return [
        {
            "path": page.path,
            "anchor_text": recommendation.anchor_text,
            "reason": recommendation.reason,
        }
        for recommendation, page in rows
    ]


async def create_brief(db: AsyncSession, *, workspace_id: uuid.UUID, site_id: uuid.UUID, data: ContentBriefCreate) -> ContentBrief:
    await _site(db, workspace_id, site_id)
    opportunity = None
    if data.opportunity_id:
        opportunity = await db.scalar(select(ContentOpportunity).where(ContentOpportunity.id == data.opportunity_id, ContentOpportunity.site_id == site_id, ContentOpportunity.workspace_id == workspace_id))
        if not opportunity:
            raise ContentCreationError("Content opportunity not found", 404)
    page = None
    if data.page_id:
        page = await db.scalar(select(Page).where(Page.id == data.page_id, Page.site_id == site_id))
        if not page:
            raise ContentCreationError("Target page not found", 404)
    insight = None
    if page:
        insight = await db.scalar(select(ContentInsight).where(ContentInsight.site_id == site_id, ContentInsight.page_id == page.id))
    target_query = data.target_query or (opportunity.target_query if opportunity else None) or (page.title if page else None) or data.topic
    title = (data.topic or (opportunity.title if opportunity else None) or (page.title if page else None) or target_query or "Untitled content brief").strip()
    topics = _terms((insight.topics if insight else []) + ([target_query] if target_query else []))
    entities = _terms(insight.entities if insight else [])
    link_rows = list((await db.execute(
        select(InternalLinkRecommendation, Page)
        .join(Page, Page.id == InternalLinkRecommendation.target_page_id)
        .where(
            InternalLinkRecommendation.site_id == site_id,
            InternalLinkRecommendation.status == "active",
        )
        .order_by(desc(InternalLinkRecommendation.priority_score))
        .limit(8)
    )).all())
    link_targets = _serialize_internal_link_targets(link_rows)
    evidence = list((opportunity.evidence if opportunity else []) or [])
    if insight:
        evidence.append({"signal": "content_insight", "page_path": page.path, "decay_score": insight.decay_score, "information_gain_score": insight.information_gain_score, "metrics": insight.metrics or {}})
    outline = [
        {"heading": title, "purpose": "Answer the primary intent directly and establish the reader's context."},
        {"heading": f"What to know about {target_query or title}", "purpose": "Define the problem with a concise, evidence-backed explanation."},
        {"heading": "How to evaluate the right approach", "purpose": "Add decision criteria and practical trade-offs that generic pages omit."},
        {"heading": "A practical workflow", "purpose": "Give the reader an actionable sequence, example, or implementation path."},
        {"heading": "Common mistakes and edge cases", "purpose": "Add information gain through failure modes and exceptions."},
    ]
    brief = ContentBrief(
        workspace_id=workspace_id, site_id=site_id, opportunity_id=opportunity.id if opportunity else None, page_id=page.id if page else None,
        status="ready", title=title, target_query=target_query, search_intent="informational", page_type=data.page_type,
        audience=data.audience or "A reader evaluating this problem and looking for a reliable next step.",
        business_goal=data.business_goal or "Earn qualified organic visibility and move the reader toward the product or next action.",
        outline=outline, required_topics=topics, required_entities=entities, internal_link_targets=link_targets,
        faq_questions=[f"What is {target_query or title}?", f"How should someone evaluate {target_query or title}?", f"What mistakes should be avoided?"],
        schema_recommendations=["Article", "FAQPage only when the visible page contains the same questions and answers"],
        information_gain=["Include a concrete example or decision framework.", "State trade-offs and edge cases instead of repeating generic definitions.", "Cite first-party evidence or clearly label assumptions."],
        evidence=evidence, scores={"priority": opportunity.priority_score if opportunity else 60, "confidence": opportunity.confidence_score if opportunity else 55, "effort": opportunity.effort_score if opportunity else 55},
    )
    db.add(brief)
    if opportunity:
        opportunity.status = "briefed"
    await db.commit()
    await db.refresh(brief)
    return brief


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:120]


def _scaffold(brief: ContentBrief) -> tuple[str, str, str]:
    sections = [f"# {brief.title}", "", f"> Drafted from search evidence for **{brief.target_query or brief.title}**. Validate claims and replace placeholders before publishing.", ""]
    for item in brief.outline or []:
        heading = item.get("heading", "")
        if not heading or heading == brief.title:
            continue
        sections.extend([f"## {heading}", "", f"{item.get('purpose', 'Explain this section with a specific example and a clear takeaway.')}", "", "Add first-party evidence, an example, and the decision this section helps the reader make.", ""])
    if brief.internal_link_targets:
        sections.extend(["## Continue exploring", "", *[f"- [{item.get('anchor_text') or item.get('path')}]({item.get('path')})" for item in brief.internal_link_targets[:5]], ""])
    sections.extend(["## Frequently asked questions", "", *[f"### {question}\n\nAnswer this question directly in 2–4 sentences." for question in (brief.faq_questions or [])], ""])
    body = "\n".join(sections)
    meta_title = brief.title[:60]
    meta_description = f"A practical, evidence-backed guide to {brief.target_query or brief.title}. Learn the trade-offs, workflow, and next steps."[:155]
    return body, meta_title, meta_description


async def _ai_draft(db: AsyncSession, *, workspace_id: uuid.UUID, site_id: uuid.UUID, brief: ContentBrief) -> str | None:
    prompt = f"""Create a concise Markdown draft from this evidence-backed SEO brief. Do not invent statistics or claims. Use placeholders where first-party proof is missing.\nTitle: {brief.title}\nQuery: {brief.target_query}\nOutline: {brief.outline}\nRequired topics: {brief.required_topics}\nEvidence: {brief.evidence}\nReturn only Markdown."""
    try:
        result = await request_ai(workspace_id=workspace_id, site_id=site_id, purpose="content_generation", messages=[{"role": "system", "content": "You are a careful SEO editor. Evidence and usefulness matter more than word count."}, {"role": "user", "content": prompt}], max_tokens=2400, db=db)
        choices = result.data.get("choices") or []
        content = choices[0].get("message", {}).get("content") if choices and isinstance(choices[0], dict) else None
        return content.strip() if isinstance(content, str) and len(content.strip()) > 100 else None
    except (AIGatewayError, KeyError, TypeError, IndexError):
        return None


async def generate_draft(db: AsyncSession, *, workspace_id: uuid.UUID, site_id: uuid.UUID, brief_id: uuid.UUID, mode: str) -> ContentDraft:
    await _site(db, workspace_id, site_id)
    brief = await db.scalar(select(ContentBrief).where(ContentBrief.id == brief_id, ContentBrief.site_id == site_id, ContentBrief.workspace_id == workspace_id))
    if not brief:
        raise ContentCreationError("Content brief not found", 404)
    body, meta_title, meta_description = _scaffold(brief)
    generation_mode = "evidence_scaffold"
    if mode == "ai_assisted":
        generated = await _ai_draft(db, workspace_id=workspace_id, site_id=site_id, brief=brief)
        if generated:
            body = generated
            generation_mode = "ai_assisted"
    draft = await db.scalar(select(ContentDraft).where(ContentDraft.brief_id == brief.id, ContentDraft.status.not_in(["archived"])).order_by(desc(ContentDraft.version)))
    if not draft:
        draft = ContentDraft(workspace_id=workspace_id, site_id=site_id, brief_id=brief.id, title=brief.title, slug=_slug(brief.title))
        db.add(draft)
    previous_body = draft.body_markdown if draft else None
    draft.title = brief.title
    draft.meta_title = meta_title
    draft.meta_description = meta_description
    draft.body_markdown = body
    draft.generation_mode = generation_mode
    draft.word_count = len(re.findall(r"\b[\w'-]+\b", body))
    is_new_version = previous_body != body or not draft.id
    draft.version = _next_draft_version(
        draft.version,
        is_new_version=is_new_version,
        has_persisted_id=bool(draft.id),
    )
    if is_new_version:
        db.add(ContentDraftVersion(draft=draft, version=draft.version, title=draft.title, meta_title=meta_title, meta_description=meta_description, body_markdown=body, generation_mode=generation_mode))
    draft.status = "draft"
    await db.commit()
    await db.refresh(draft)
    return draft


def _quality(draft: ContentDraft, brief: ContentBrief) -> dict[str, Any]:
    body = draft.body_markdown or ""
    words = draft.word_count or len(re.findall(r"\b[\w'-]+\b", body))
    checks = [
        {"key": "title_length", "label": "Title length", "passed": 20 <= len(draft.meta_title) <= 60, "detail": f"{len(draft.meta_title)} characters; target 20–60."},
        {"key": "meta_description", "label": "Meta description", "passed": 80 <= len(draft.meta_description) <= 160, "detail": f"{len(draft.meta_description)} characters; target 80–160."},
        {"key": "word_count", "label": "Substantive draft", "passed": words >= 450, "detail": f"{words} words; expand with proof and examples before publishing."},
        {"key": "outline_coverage", "label": "Brief coverage", "passed": sum(1 for item in (brief.outline or []) if item.get("heading", "").lower() in body.lower()) >= max(1, len(brief.outline or []) // 2), "detail": "The draft should cover the brief's recommended sections."},
        {"key": "information_gain", "label": "Information gain", "passed": any(marker in body.lower() for marker in ["example", "trade-off", "mistake", "workflow"]), "detail": "Add original examples, trade-offs, or edge cases."},
        {"key": "internal_links", "label": "Internal links", "passed": not brief.internal_link_targets or any(item.get("path", "") in body for item in brief.internal_link_targets), "detail": "Use relevant existing pages where a link helps the reader."},
        {"key": "evidence_boundary", "label": "Evidence boundary", "passed": "placeholder" in body.lower() or bool(brief.evidence), "detail": "Claims should be backed by evidence or clearly marked for review."},
    ]
    passed = sum(1 for item in checks if item["passed"])
    return {"overall_score": round(passed / len(checks) * 100), "passed": passed == len(checks), "checks": checks}


async def run_quality_check(db: AsyncSession, *, workspace_id: uuid.UUID, site_id: uuid.UUID, draft_id: uuid.UUID) -> ContentQualityCheck:
    draft = await db.scalar(select(ContentDraft).where(ContentDraft.id == draft_id, ContentDraft.site_id == site_id, ContentDraft.workspace_id == workspace_id))
    if not draft:
        raise ContentCreationError("Content draft not found", 404)
    brief = await db.scalar(select(ContentBrief).where(ContentBrief.id == draft.brief_id, ContentBrief.workspace_id == workspace_id))
    if not brief:
        raise ContentCreationError("Content brief not found", 404)
    result = _quality(draft, brief)
    check = ContentQualityCheck(workspace_id=workspace_id, site_id=site_id, draft_id=draft.id, overall_score=result["overall_score"], passed=result["passed"], checks=result["checks"])
    draft.quality_summary = {"overall_score": check.overall_score, "passed": check.passed, "checks": check.checks}
    db.add(check)
    await db.commit()
    await db.refresh(check)
    return check


async def update_draft(db: AsyncSession, *, workspace_id: uuid.UUID, site_id: uuid.UUID, draft_id: uuid.UUID, data: ContentDraftUpdate) -> ContentDraft:
    draft = await db.scalar(select(ContentDraft).where(ContentDraft.id == draft_id, ContentDraft.site_id == site_id, ContentDraft.workspace_id == workspace_id))
    if not draft:
        raise ContentCreationError("Content draft not found", 404)
    if draft.status == "awaiting_approval":
        raise ContentCreationError("Withdraw the draft from approval before editing it", 409)
    draft.version = _next_draft_version(
        draft.version,
        is_new_version=True,
        has_persisted_id=True,
    )
    draft.title = data.title.strip()
    draft.meta_title = data.meta_title.strip()
    draft.meta_description = data.meta_description.strip()
    draft.body_markdown = data.body_markdown
    draft.word_count = len(re.findall(r"\b[\w'-]+\b", draft.body_markdown))
    draft.status = "draft"
    db.add(ContentDraftVersion(draft_id=draft.id, version=draft.version, title=draft.title, meta_title=draft.meta_title, meta_description=draft.meta_description, body_markdown=draft.body_markdown, generation_mode="manual"))
    await db.commit()
    await db.refresh(draft)
    return draft


async def submit_for_approval(db: AsyncSession, *, workspace_id: uuid.UUID, user_id: uuid.UUID, site_id: uuid.UUID, draft_id: uuid.UUID) -> ContentDraft:
    draft = await db.scalar(select(ContentDraft).where(ContentDraft.id == draft_id, ContentDraft.site_id == site_id, ContentDraft.workspace_id == workspace_id))
    if not draft:
        raise ContentCreationError("Content draft not found", 404)
    brief = await db.scalar(select(ContentBrief).where(ContentBrief.id == draft.brief_id, ContentBrief.workspace_id == workspace_id))
    if not brief:
        raise ContentCreationError("Content brief not found", 404)
    result = _quality(draft, brief)
    if result["overall_score"] < 50:
        raise ContentCreationError("Run quality checks and resolve the core draft gaps before approval", 409)
    action = await create_action(db, workspace_id=workspace_id, user_id=user_id, data=OperatorActionCreate(
        site_id=site_id, action_type="content_draft", category="content", source="serp_content", title=f"Review and publish: {draft.title}",
        description="Review this evidence-backed content draft. Publishing remains approval-gated and adapter-controlled.",
        evidence=[*brief.evidence, {"signal": "quality_check", "score": result["overall_score"], "passed": result["passed"]}],
        plan={"draft_id": str(draft.id), "brief_id": str(brief.id), "steps": ["Review factual claims", "Edit for brand voice", "Approve a CMS or repository target", "Publish only through the governed adapter"]},
        impact_score=int((brief.scores or {}).get("priority", 60)), confidence_score=int((brief.scores or {}).get("confidence", 55)), effort_score=int((brief.scores or {}).get("effort", 55)), risk_score=55,
        execution_target={"type": "content_publish", "mode": "approval_required", "adapter": "simulation"}, proposed_diff={"kind": "content_draft", "draft_id": str(draft.id), "title": draft.title, "body_markdown": draft.body_markdown},
        rollback_plan={"strategy": "restore_previous_content_version", "draft_id": str(draft.id)}, measurement_plan={"window_days": 28, "targets": [brief.target_query, brief.page_id and str(brief.page_id)]},
        validation_checklist=["Confirm target URL or repository path", "Confirm title and meta description", "Confirm visible evidence and citations", "Confirm internal links", "Run post-publish crawl and measurement"], idempotency_key=f"content-draft:{draft.id}:v{draft.version}"))
    draft.action_id = action.id
    draft.status = "awaiting_approval"
    await db.commit()
    await db.refresh(draft)
    return draft


async def get_workspace(db: AsyncSession, *, workspace_id: uuid.UUID, site_id: uuid.UUID) -> dict[str, Any]:
    rows = await sync_opportunities(db, workspace_id=workspace_id, site_id=site_id)
    opportunity_payload = await _opportunity_payload(db, rows)
    await db.commit()
    briefs = list((await db.execute(select(ContentBrief).where(ContentBrief.site_id == site_id, ContentBrief.workspace_id == workspace_id).order_by(desc(ContentBrief.updated_at)).limit(50))).scalars().all())
    drafts = list((await db.execute(select(ContentDraft).where(ContentDraft.site_id == site_id, ContentDraft.workspace_id == workspace_id).order_by(desc(ContentDraft.updated_at)).limit(50))).scalars().all())
    return {"opportunities": opportunity_payload, "briefs": [_brief_dict(row) for row in briefs], "drafts": [_draft_dict(row) for row in drafts], "counts": {"opportunities": len(opportunity_payload), "briefs": len(briefs), "drafts": len(drafts), "awaiting_approval": sum(1 for row in drafts if row.status == "awaiting_approval")}}


async def list_briefs(db: AsyncSession, *, workspace_id: uuid.UUID, site_id: uuid.UUID) -> list[dict[str, Any]]:
    await _site(db, workspace_id, site_id)
    rows = list((await db.execute(select(ContentBrief).where(ContentBrief.site_id == site_id, ContentBrief.workspace_id == workspace_id).order_by(desc(ContentBrief.updated_at)).limit(100))).scalars().all())
    return [_brief_dict(row) for row in rows]


async def list_drafts(db: AsyncSession, *, workspace_id: uuid.UUID, site_id: uuid.UUID) -> list[dict[str, Any]]:
    await _site(db, workspace_id, site_id)
    rows = list((await db.execute(select(ContentDraft).where(ContentDraft.site_id == site_id, ContentDraft.workspace_id == workspace_id).order_by(desc(ContentDraft.updated_at)).limit(100))).scalars().all())
    return [_draft_dict(row) for row in rows]


def quality_to_dict(item: ContentQualityCheck) -> dict[str, Any]:
    return {"id": item.id, "draft_id": item.draft_id, "overall_score": item.overall_score, "passed": item.passed, "checks": item.checks or [], "created_at": item.created_at}
