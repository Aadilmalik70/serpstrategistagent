from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.crawl_snapshot import CrawlSnapshot
from app.models.issue import Issue
from app.models.operator_action import OperatorAction, OperatorActionEvent
from app.models.page import Page
from app.models.site import Site
from app.schemas.operator_action import OperatorActionCreate
from app.services import github_patch_planner
from app.services.github_patch_planner import PLANNER_VERSION, RepositoryPatchPlan
from app.services.operator_action_service import cancel_action, create_action, propose_action


DETECTOR_VERSION = "first-party-v1"
ACTIVE_FINDING_STATUSES = ("open", "regressed")


@dataclass(frozen=True)
class FindingCandidate:
    finding_type: str
    category: str
    severity: str
    title: str
    description: str
    recommendation: str
    affected_urls: tuple[str, ...]
    evidence: tuple[dict[str, Any], ...]
    impact_score: int
    confidence_score: int
    effort_score: int
    page_id: uuid.UUID | None = None
    identity: str = ""
    action_type: str | None = None
    action_risk_score: int = 0
    execution_target: dict[str, Any] = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        urls = "|".join(sorted(set(self.affected_urls)))
        raw = f"{DETECTOR_VERSION}|{self.finding_type}|{self.identity}|{urls}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _candidate(
    page: Page,
    *,
    finding_type: str,
    severity: str,
    title: str,
    description: str,
    recommendation: str,
    impact: int,
    confidence: int,
    effort: int,
    action_type: str | None,
    risk: int = 10,
    category: str = "technical",
    evidence: dict[str, Any] | None = None,
) -> FindingCandidate:
    observation = {
        "type": "crawl_observation",
        "finding_type": finding_type,
        "url": page.path,
        "status_code": page.status_code,
        "observed": evidence or {},
    }
    return FindingCandidate(
        finding_type=finding_type,
        category=category,
        severity=severity,
        title=title,
        description=description,
        recommendation=recommendation,
        affected_urls=(page.path,),
        evidence=(observation,),
        impact_score=impact,
        confidence_score=confidence,
        effort_score=effort,
        page_id=page.id,
        action_type=action_type,
        action_risk_score=risk,
        execution_target={"adapter": "simulation", "resource": "page", "url": page.path},
    )


def detect_page_findings(page: Page) -> list[FindingCandidate]:
    findings: list[FindingCandidate] = []
    metadata = page.meta or {}
    status = int(page.status_code or 0)

    if status == 200 and not (page.title or "").strip():
        findings.append(_candidate(
            page,
            finding_type="missing_title",
            severity="critical",
            title="Missing page title",
            description=f"{page.path} has no title element.",
            recommendation="Add a unique, descriptive title between 30 and 60 characters.",
            impact=95,
            confidence=100,
            effort=15,
            action_type="metadata_update",
        ))
    elif page.title and len(page.title.strip()) > 60:
        findings.append(_candidate(
            page,
            finding_type="title_too_long",
            severity="medium",
            title="Title tag is longer than 60 characters",
            description=f"{page.path} has a {len(page.title.strip())}-character title.",
            recommendation="Shorten the title while preserving its primary topic and intent.",
            impact=55,
            confidence=99,
            effort=15,
            action_type="metadata_update",
            evidence={"title": page.title, "length": len(page.title.strip())},
        ))
    elif page.title and len(page.title.strip()) < 20:
        findings.append(_candidate(
            page,
            finding_type="title_too_short",
            severity="low",
            title="Title tag is shorter than 20 characters",
            description=f"{page.path} has a {len(page.title.strip())}-character title.",
            recommendation="Make the title more descriptive without keyword stuffing.",
            impact=30,
            confidence=95,
            effort=15,
            action_type="metadata_update",
            evidence={"title": page.title, "length": len(page.title.strip())},
        ))

    if status == 200 and not (page.meta_description or "").strip():
        findings.append(_candidate(
            page,
            finding_type="missing_meta_description",
            severity="high",
            title="Missing meta description",
            description=f"{page.path} does not provide a meta description.",
            recommendation="Add a page-specific description that accurately summarizes the search result.",
            impact=75,
            confidence=100,
            effort=20,
            action_type="metadata_update",
        ))
    elif page.meta_description and len(page.meta_description.strip()) > 160:
        findings.append(_candidate(
            page,
            finding_type="meta_description_too_long",
            severity="low",
            title="Meta description is longer than 160 characters",
            description=f"{page.path} has a {len(page.meta_description.strip())}-character description.",
            recommendation="Shorten the description while preserving its value proposition.",
            impact=35,
            confidence=99,
            effort=15,
            action_type="metadata_update",
            evidence={"length": len(page.meta_description.strip())},
        ))

    h1_count = int(metadata.get("h1_count") or (1 if page.h1 else 0))
    if status == 200 and h1_count == 0:
        findings.append(_candidate(
            page,
            finding_type="missing_h1",
            severity="high",
            title="Missing H1 heading",
            description=f"{page.path} has no H1 heading.",
            recommendation="Add one descriptive H1 that matches the page's primary intent.",
            impact=70,
            confidence=99,
            effort=25,
            action_type="content_refresh_draft",
        ))
    elif status == 200 and h1_count > 1:
        findings.append(_candidate(
            page,
            finding_type="multiple_h1",
            severity="medium",
            title="Multiple H1 headings",
            description=f"{page.path} contains {h1_count} H1 headings.",
            recommendation="Use one primary H1 and demote subordinate headings where appropriate.",
            impact=45,
            confidence=99,
            effort=25,
            action_type="content_refresh_draft",
            evidence={"h1_count": h1_count},
        ))

    robots = str(metadata.get("robots") or "").lower()
    if status == 200 and "noindex" in robots:
        findings.append(_candidate(
            page,
            finding_type="noindex_directive",
            severity="critical",
            title="Page is excluded by a noindex directive",
            description=f"{page.path} returns a noindex directive.",
            recommendation="Confirm intent; remove noindex only when this page should appear in search.",
            impact=95,
            confidence=100,
            effort=20,
            action_type="indexability_update",
            risk=75,
            evidence={"robots": robots},
        ))

    if status == 200 and not page.canonical_url:
        findings.append(_candidate(
            page,
            finding_type="missing_canonical",
            severity="medium",
            title="Missing canonical URL",
            description=f"{page.path} has no canonical link element.",
            recommendation="Add a self-referencing canonical unless another preferred URL is intentional.",
            impact=55,
            confidence=100,
            effort=20,
            action_type="canonical_update",
            risk=40,
        ))

    if status == 200 and not metadata.get("viewport"):
        findings.append(_candidate(
            page,
            finding_type="missing_viewport",
            severity="high",
            title="Missing mobile viewport declaration",
            description=f"{page.path} has no viewport meta tag.",
            recommendation="Add a responsive width=device-width viewport declaration.",
            impact=70,
            confidence=100,
            effort=10,
            action_type="metadata_update",
        ))

    if status == 404:
        sources = list(metadata.get("linked_from") or [])
        findings.append(_candidate(
            page,
            finding_type="internal_404",
            severity="high",
            title="Internal URL returns 404",
            description=f"{page.path} returns HTTP 404 and is linked from {len(sources)} crawled page(s).",
            recommendation="Restore the page, redirect it to the closest equivalent, or remove its internal links.",
            impact=80,
            confidence=100,
            effort=40,
            action_type="redirect_update",
            risk=45,
            evidence={"linked_from": sources[:50]},
        ))

    redirect_chain = list(metadata.get("redirect_chain") or [])
    if len(redirect_chain) > 1:
        findings.append(_candidate(
            page,
            finding_type="redirect_chain",
            severity="medium",
            title="Redirect chain detected",
            description=f"{page.path} resolves through {len(redirect_chain)} redirects.",
            recommendation="Update internal references to point directly to the final URL.",
            impact=50,
            confidence=100,
            effort=30,
            action_type="redirect_update",
            risk=45,
            evidence={"chain": redirect_chain},
        ))

    linked_from = list(metadata.get("linked_from") or [])
    if status == 200 and page.path != "/" and not linked_from:
        findings.append(_candidate(
            page,
            finding_type="orphan_page",
            severity="medium",
            title="Page has no discovered internal links",
            description=f"{page.path} was discovered without an internal inlink from another crawled page.",
            recommendation="Add relevant contextual internal links from established pages.",
            impact=60,
            confidence=90,
            effort=30,
            action_type="internal_link_add",
        ))

    if page.path == "/" and status == 200 and int(metadata.get("json_ld_count") or 0) == 0:
        findings.append(_candidate(
            page,
            finding_type="missing_homepage_structured_data",
            severity="low",
            title="Homepage has no JSON-LD structured data",
            description="The homepage does not expose JSON-LD entities for search engines.",
            recommendation="Add valid Organization or WebSite schema that reflects visible content.",
            impact=35,
            confidence=95,
            effort=30,
            action_type="schema_add",
        ))

    images_without_alt = int(metadata.get("images_without_alt") or 0)
    if status == 200 and images_without_alt > 0:
        findings.append(_candidate(
            page,
            finding_type="images_missing_alt",
            severity="medium",
            title="Images are missing alternative text",
            description=f"{page.path} contains {images_without_alt} image(s) without alt text.",
            recommendation="Add concise alt text to informative images and empty alt attributes to decorative images.",
            impact=45,
            confidence=100,
            effort=30,
            action_type="content_refresh_draft",
            category="accessibility",
            evidence={"images_without_alt": images_without_alt},
        ))

    if status == 200 and page.word_count is not None and page.word_count < 200:
        findings.append(_candidate(
            page,
            finding_type="thin_content",
            severity="medium",
            title="Very little indexable content",
            description=f"{page.path} contains approximately {page.word_count} visible words.",
            recommendation="Review search intent and add useful, non-repetitive information where warranted.",
            impact=55,
            confidence=85,
            effort=65,
            action_type="content_refresh_draft",
            category="content",
            evidence={"word_count": page.word_count},
        ))

    if page.response_time_ms and page.response_time_ms > 3000:
        findings.append(_candidate(
            page,
            finding_type="slow_initial_response",
            severity="high",
            title="Slow initial server response",
            description=f"{page.path} took {page.response_time_ms} ms to respond during the crawl.",
            recommendation="Validate with repeated measurements, then review caching, origin latency, and backend work.",
            impact=70,
            confidence=80,
            effort=70,
            action_type="recommendation",
            risk=35,
            category="performance",
            evidence={"response_time_ms": page.response_time_ms},
        ))

    return findings


def detect_cross_page_findings(pages: list[Page]) -> list[FindingCandidate]:
    findings: list[FindingCandidate] = []
    for field_name, finding_type, severity, label in (
        ("title", "duplicate_title", "high", "title tag"),
        ("meta_description", "duplicate_meta_description", "medium", "meta description"),
    ):
        values: dict[str, list[Page]] = {}
        for page in pages:
            value = str(getattr(page, field_name) or "").strip()
            if page.status_code == 200 and value:
                values.setdefault(value.casefold(), []).append(page)
        for normalized, matching in values.items():
            if len(matching) < 2:
                continue
            urls = tuple(sorted(page.path for page in matching))
            findings.append(FindingCandidate(
                finding_type=finding_type,
                category="technical",
                severity=severity,
                title=f"Duplicate {label}",
                description=f"The same {label} is used by {len(urls)} crawled pages.",
                recommendation=f"Give every indexable page a unique {label} aligned to its intent.",
                affected_urls=urls,
                evidence=({"type": "cross_page_comparison", "field": field_name, "value": normalized, "urls": list(urls)},),
                impact_score=75 if finding_type == "duplicate_title" else 55,
                confidence_score=100,
                effort_score=min(80, 15 + len(urls) * 5),
                identity=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
                action_type="metadata_update",
                action_risk_score=20,
                execution_target={"adapter": "simulation", "resource": "page_metadata", "urls": list(urls)},
            ))
    return findings


def detect_crawl_findings(snapshot: CrawlSnapshot | None) -> list[FindingCandidate]:
    if not snapshot or snapshot.status != "completed":
        return []
    data = snapshot.extracted_data or {}
    findings: list[FindingCandidate] = []
    robots = data.get("robots") or {}
    if robots.get("status_code") and int(robots["status_code"]) >= 400:
        findings.append(FindingCandidate(
            finding_type="missing_robots_txt",
            category="technical",
            severity="high",
            title="robots.txt is unavailable",
            description=f"The crawler received HTTP {robots['status_code']} for robots.txt.",
            recommendation="Publish a valid robots.txt with an explicit sitemap reference.",
            affected_urls=("/robots.txt",),
            evidence=({"type": "crawl_artifact", "robots": robots},),
            impact_score=70,
            confidence_score=100,
            effort_score=25,
            action_type="robots_update",
            action_risk_score=85,
            execution_target={"adapter": "simulation", "path": "robots.txt"},
        ))
    sitemap = data.get("sitemap") or {}
    if sitemap.get("errors") and not sitemap.get("urls_discovered"):
        findings.append(FindingCandidate(
            finding_type="missing_or_invalid_sitemap",
            category="technical",
            severity="high",
            title="No usable XML sitemap was discovered",
            description="The crawl could not discover URLs from the configured or conventional sitemap locations.",
            recommendation="Publish a valid sitemap and reference it from robots.txt.",
            affected_urls=("/sitemap.xml",),
            evidence=({"type": "crawl_artifact", "sitemap": sitemap},),
            impact_score=70,
            confidence_score=95,
            effort_score=35,
            action_type="sitemap_update",
            action_risk_score=45,
            execution_target={"adapter": "simulation", "path": "sitemap.xml"},
        ))
    return findings


async def collect_candidates(db: AsyncSession, site_id: uuid.UUID) -> tuple[list[FindingCandidate], CrawlSnapshot | None]:
    pages = list((await db.execute(select(Page).where(Page.site_id == site_id).order_by(Page.path))).scalars().all())
    snapshot = await db.scalar(
        select(CrawlSnapshot)
        .where(CrawlSnapshot.site_id == site_id)
        .order_by(CrawlSnapshot.started_at.desc())
        .limit(1)
    )
    candidates = [candidate for page in pages for candidate in detect_page_findings(page)]
    candidates.extend(detect_cross_page_findings(pages))
    candidates.extend(detect_crawl_findings(snapshot))
    return candidates, snapshot


def _apply_candidate(
    finding: Issue,
    candidate: FindingCandidate,
    *,
    run_id: uuid.UUID | None,
    crawl_id: uuid.UUID | None,
    now: datetime,
) -> None:
    finding.page_id = candidate.page_id
    finding.agent_run_id = run_id
    finding.source_crawl_id = crawl_id
    finding.finding_type = candidate.finding_type
    finding.detector_version = DETECTOR_VERSION
    finding.category = candidate.category
    finding.severity = candidate.severity
    finding.title = candidate.title
    finding.description = candidate.description
    finding.recommendation = candidate.recommendation
    finding.affected_urls = list(candidate.affected_urls)
    finding.affected_url = candidate.affected_urls[0] if candidate.affected_urls else None
    finding.evidence = list(candidate.evidence)
    finding.impact_score = candidate.impact_score
    finding.confidence_score = candidate.confidence_score
    finding.effort_score = candidate.effort_score
    finding.last_seen_at = now
    finding.meta = {
        **(finding.meta or {}),
        "action": {
            "action_type": candidate.action_type,
            "risk_score": candidate.action_risk_score,
            "execution_target": candidate.execution_target,
        },
    }


async def reconcile_findings(
    db: AsyncSession,
    *,
    site_id: uuid.UUID,
    run_id: uuid.UUID | None,
    snapshot: CrawlSnapshot | None,
    candidates: list[FindingCandidate],
) -> tuple[dict[str, int], list[Issue], list[Issue]]:
    now = datetime.now(timezone.utc)
    existing = {
        finding.fingerprint: finding
        for finding in (
            await db.execute(select(Issue).where(Issue.site_id == site_id))
        ).scalars().all()
    }
    seen: set[str] = set()
    actionable: list[Issue] = []
    resolved: list[Issue] = []
    counts = {"created": 0, "updated": 0, "regressed": 0, "resolved": 0}

    for candidate in candidates:
        fingerprint = candidate.fingerprint
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        finding = existing.get(fingerprint)
        if finding is None:
            finding = Issue(
                site_id=site_id,
                fingerprint=fingerprint,
                finding_type=candidate.finding_type,
                detector_version=DETECTOR_VERSION,
                category=candidate.category,
                severity=candidate.severity,
                title=candidate.title,
                description=candidate.description,
                status="open",
                first_seen_at=now,
                last_seen_at=now,
                occurrence_count=1,
                regression_count=0,
            )
            db.add(finding)
            counts["created"] += 1
            actionable.append(finding)
        else:
            previous_status = finding.status
            finding.occurrence_count = int(finding.occurrence_count or 0) + 1
            if previous_status in {"resolved", "fixed"}:
                finding.status = "regressed"
                finding.regression_count = int(finding.regression_count or 0) + 1
                finding.resolved_at = None
                counts["regressed"] += 1
                actionable.append(finding)
            elif previous_status != "dismissed":
                finding.status = "regressed" if previous_status == "regressed" else "open"
                counts["updated"] += 1
        _apply_candidate(
            finding,
            candidate,
            run_id=run_id,
            crawl_id=snapshot.id if snapshot else None,
            now=now,
        )

    for fingerprint, finding in existing.items():
        if fingerprint in seen or finding.status not in ACTIVE_FINDING_STATUSES:
            continue
        finding.status = "resolved"
        finding.resolved_at = now
        counts["resolved"] += 1
        resolved.append(finding)

    await db.commit()
    for finding in actionable:
        await db.refresh(finding)
    return counts, actionable, resolved


def _action_data(
    finding: Issue,
    patch_plan: RepositoryPatchPlan | None = None,
) -> OperatorActionCreate | None:
    action_config = (finding.meta or {}).get("action") or {}
    action_type = action_config.get("action_type")
    if not action_type:
        return None
    affected_urls = list(finding.affected_urls or ([finding.affected_url] if finding.affected_url else []))
    affected_pages = len(affected_urls)
    execution_target = dict(action_config.get("execution_target") or {"adapter": "simulation"})
    proposed_diff: dict[str, Any] = {
        "summary": finding.recommendation,
        "affected_pages": affected_pages,
        "affected_urls": affected_urls,
        "mode": "simulation_until_exact_patch_ready",
        "planner": {
            "status": patch_plan.status if patch_plan else "fallback",
            "version": PLANNER_VERSION,
            "reason_code": patch_plan.reason_code if patch_plan else "planning_not_attempted",
            "reason": patch_plan.reason if patch_plan else "Repository patch planning was not attempted.",
        },
    }
    rollback_plan: dict[str, Any] = {
        "strategy": "restore_before_snapshot",
        "required": True,
        "note": "Simulation actions do not mutate the mapped repository.",
    }
    if patch_plan and patch_plan.ready:
        execution_target = dict(patch_plan.execution_target)
        proposed_diff = dict(patch_plan.proposed_diff)
        rollback_plan = dict(patch_plan.rollback_plan)

    idempotency_key = f"finding:{finding.fingerprint}:r{finding.regression_count}"
    if patch_plan and patch_plan.ready:
        planner = proposed_diff.get("planner") if isinstance(proposed_diff.get("planner"), dict) else {}
        expected_sha = str(planner.get("expected_sha") or "")[:12]
        idempotency_key = (
            f"finding:{finding.fingerprint}:r{finding.regression_count}:github:{expected_sha}"
        )

    return OperatorActionCreate(
        site_id=finding.site_id,
        issue_id=finding.id,
        action_type=str(action_type),
        category=finding.category,
        source="technical_finding_pipeline",
        title=f"Resolve: {finding.title}",
        description=finding.recommendation or finding.description,
        evidence=[
            *list(finding.evidence or []),
            {
                "type": "technical_finding",
                "finding_id": str(finding.id),
                "fingerprint": finding.fingerprint,
                "detector_version": finding.detector_version,
                "status": finding.status,
            },
        ],
        plan={
            "objective": finding.recommendation,
            "steps": [
                "capture the current page and integration state",
                "prepare the smallest reversible change",
                "run policy and approval checks",
                "validate the affected URLs after deployment",
            ],
            "affected_urls": affected_urls,
        },
        impact_score=finding.impact_score,
        confidence_score=finding.confidence_score,
        effort_score=finding.effort_score,
        risk_score=int(action_config.get("risk_score") or 0),
        execution_target=execution_target,
        proposed_diff=proposed_diff,
        rollback_plan=rollback_plan,
        measurement_plan={
            "windows_days": [7, 14, 30],
            "metrics": ["finding_status", "indexed_pages", "clicks", "impressions", "ctr"],
            "success": "finding is absent on a later crawl without negative search-performance movement",
        },
        validation_checklist=[
            "the affected URL remains reachable",
            "the detector no longer reproduces the finding",
            "indexability and canonical intent remain valid",
            "the build or CMS validation succeeds before shipment",
        ],
        idempotency_key=idempotency_key,
    )


async def _cancel_superseded_simulation_actions(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    finding: Issue,
    keep_action_id: uuid.UUID,
) -> None:
    previous_actions = list((await db.execute(
        select(OperatorAction).where(
            OperatorAction.workspace_id == workspace_id,
            OperatorAction.issue_id == finding.id,
            OperatorAction.id != keep_action_id,
            OperatorAction.status.in_(["draft", "needs_approval", "approved"]),
        )
    )).scalars().all())
    for previous in previous_actions:
        adapter = str((previous.execution_target or {}).get("adapter") or "").strip().lower()
        if adapter != "simulation":
            continue
        await cancel_action(
            db,
            workspace_id=workspace_id,
            user_id=None,
            action_id=previous.id,
            expected_version=previous.version,
        )


async def _refresh_simulation_fallback_metadata(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    action: OperatorAction,
    data: OperatorActionCreate,
) -> None:
    adapter = str((action.execution_target or {}).get("adapter") or "").strip().lower()
    if adapter != "simulation" or action.status not in {"draft", "needs_approval", "approved"}:
        return
    proposed_diff = data.proposed_diff or {}
    rollback_plan = data.rollback_plan or {}
    if action.proposed_diff == proposed_diff and action.rollback_plan == rollback_plan:
        return

    action.proposed_diff = proposed_diff
    action.rollback_plan = rollback_plan
    action.version += 1
    planner = proposed_diff.get("planner") if isinstance(proposed_diff, dict) else {}
    if not isinstance(planner, dict):
        planner = {}
    db.add(
        OperatorActionEvent(
            action_id=action.id,
            workspace_id=workspace_id,
            site_id=action.site_id,
            event_type="action_plan_refreshed",
            from_status=action.status,
            to_status=action.status,
            actor_user_id=None,
            actor_type="system",
            payload={
                "adapter": "simulation",
                "planner_status": planner.get("status"),
                "reason_code": planner.get("reason_code"),
            },
        )
    )
    await db.commit()
    await db.refresh(action)


async def ensure_action_for_finding(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    finding: Issue,
    actor_user_id: uuid.UUID | None,
    allow_github_planning: bool = True,
) -> tuple[OperatorAction | None, bool]:
    patch_plan = (
        await github_patch_planner.plan_patch_for_finding(
            db,
            workspace_id=workspace_id,
            finding=finding,
        )
        if allow_github_planning
        else RepositoryPatchPlan.fallback(
            "github_planning_budget_exhausted",
            "This refresh reached the configured repository-planning limit.",
        )
    )
    data = _action_data(finding, patch_plan)
    if data is None:
        return None, False
    existing = await db.scalar(
        select(OperatorAction).where(
            OperatorAction.workspace_id == workspace_id,
            OperatorAction.idempotency_key == data.idempotency_key,
        )
    )
    if existing:
        if patch_plan.ready:
            await _cancel_superseded_simulation_actions(
                db,
                workspace_id=workspace_id,
                finding=finding,
                keep_action_id=existing.id,
            )
        else:
            await _refresh_simulation_fallback_metadata(
                db,
                workspace_id=workspace_id,
                action=existing,
                data=data,
            )
        return existing, False
    action = await create_action(
        db,
        workspace_id=workspace_id,
        user_id=actor_user_id,
        data=data,
    )
    action = await propose_action(
        db,
        workspace_id=workspace_id,
        user_id=actor_user_id,
        action_id=action.id,
        expected_version=action.version,
    )
    if patch_plan.ready:
        await _cancel_superseded_simulation_actions(
            db,
            workspace_id=workspace_id,
            finding=finding,
            keep_action_id=action.id,
        )
    return action, True


async def _cancel_stale_actions(db: AsyncSession, workspace_id: uuid.UUID, findings: list[Issue]) -> None:
    for finding in findings:
        actions = list((await db.execute(
            select(OperatorAction).where(
                OperatorAction.workspace_id == workspace_id,
                OperatorAction.issue_id == finding.id,
                OperatorAction.status.in_(["draft", "needs_approval", "approved"]),
            )
        )).scalars().all())
        for action in actions:
            await cancel_action(
                db,
                workspace_id=workspace_id,
                user_id=None,
                action_id=action.id,
                expected_version=action.version,
            )


async def run_technical_finding_pipeline(
    db: AsyncSession,
    *,
    site: Site,
    run_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    candidates, snapshot = await collect_candidates(db, site.id)
    counts, actionable, resolved = await reconcile_findings(
        db,
        site_id=site.id,
        run_id=run_id,
        snapshot=snapshot,
        candidates=candidates,
    )
    action_ids: list[uuid.UUID] = []
    actions_created = 0
    if site.workspace_id:
        await _cancel_stale_actions(db, site.workspace_id, resolved)
        # Ensure an interrupted prior run cannot leave an active finding without
        # its governed action. Idempotency keeps this safe on every refresh.
        active_findings = list((await db.execute(
            select(Issue).where(
                Issue.site_id == site.id,
                Issue.status.in_(ACTIVE_FINDING_STATUSES),
            )
        )).scalars().all())
        planning_attempts = 0
        planning_limit = get_settings().github_patch_planning_max_actions_per_refresh
        for finding in active_findings:
            planning_candidate = github_patch_planner.is_patch_planning_candidate(finding)
            allow_github_planning = not planning_candidate or planning_attempts < planning_limit
            if planning_candidate and allow_github_planning:
                planning_attempts += 1
            action, created = await ensure_action_for_finding(
                db,
                workspace_id=site.workspace_id,
                finding=finding,
                actor_user_id=actor_user_id,
                allow_github_planning=allow_github_planning,
            )
            if action:
                action_ids.append(action.id)
            actions_created += int(created)
    active = int(await db.scalar(
        select(func.count(Issue.id)).where(
            Issue.site_id == site.id,
            Issue.status.in_(ACTIVE_FINDING_STATUSES),
        )
    ) or 0)
    return {
        **counts,
        "active": active,
        "actions_created": actions_created,
        "action_ids": action_ids,
        "candidates": len(candidates),
        "crawl_id": snapshot.id if snapshot else None,
    }
