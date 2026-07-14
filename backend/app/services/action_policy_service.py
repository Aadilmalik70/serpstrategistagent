from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PolicyDecision:
    risk_score: int
    risk_level: str
    mode: str
    requires_approval: bool
    allowed_roles: tuple[str, ...]
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "requires_approval": self.requires_approval,
            "allowed_roles": list(self.allowed_roles),
            "reasons": list(self.reasons),
            "risk_score": self.risk_score,
            "risk_level": self.risk_level,
        }


HIGH_RISK_ACTIONS = {
    "domain_migration",
    "sitewide_redirect",
    "robots_update",
    "bulk_noindex",
    "delete_content",
    "canonical_bulk",
    "template_rewrite",
}

AUTO_APPROVABLE_ACTIONS = {
    "recommendation",
    "metadata_update",
    "internal_link_add",
    "schema_add",
    "content_refresh_draft",
}

PROTECTED_PATH_MARKERS = (
    ".github/workflows/",
    "robots.txt",
    "next.config",
    "middleware.",
    "wp-config.php",
    ".env",
)


def _target_paths(execution_target: dict[str, Any], proposed_diff: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("path", "paths", "target_path", "protected_paths"):
        raw = execution_target.get(key)
        if isinstance(raw, str):
            values.append(raw)
        elif isinstance(raw, list):
            values.extend(str(item) for item in raw)
    for key in ("path", "paths", "files_changed", "files_deleted"):
        raw = proposed_diff.get(key)
        if isinstance(raw, str):
            values.append(raw)
        elif isinstance(raw, list):
            values.extend(str(item) for item in raw)
    return [value.strip().lower() for value in values if value and str(value).strip()]


def evaluate_action_policy(
    *,
    action_type: str,
    submitted_risk_score: int,
    execution_target: dict[str, Any],
    proposed_diff: dict[str, Any],
) -> PolicyDecision:
    score = max(0, min(100, submitted_risk_score))
    reasons: list[str] = []
    normalized_type = action_type.strip().lower()

    if normalized_type in HIGH_RISK_ACTIONS:
        score = max(score, 80)
        reasons.append("Action type can affect broad site behavior")

    paths = _target_paths(execution_target, proposed_diff)
    protected_matches = [
        path
        for path in paths
        if any(marker in path for marker in PROTECTED_PATH_MARKERS)
    ]
    if protected_matches:
        score = max(score, 90)
        reasons.append("Protected or infrastructure-sensitive path is targeted")

    delete_count = proposed_diff.get("delete_count", 0)
    try:
        delete_count = int(delete_count)
    except (TypeError, ValueError):
        delete_count = 0
    if delete_count > 0:
        score = max(score, 75)
        reasons.append("Proposed diff deletes existing content or files")

    affected_pages = proposed_diff.get("affected_pages", 0)
    try:
        affected_pages = int(affected_pages)
    except (TypeError, ValueError):
        affected_pages = 0
    if affected_pages >= 100:
        score = max(score, 70)
        reasons.append("Change affects at least 100 pages")
    elif affected_pages >= 20:
        score = max(score, 45)
        reasons.append("Change affects multiple pages")

    if score >= 90:
        return PolicyDecision(
            risk_score=score,
            risk_level="high",
            mode="blocked",
            requires_approval=True,
            allowed_roles=("owner",),
            reasons=tuple(reasons or ["Risk threshold requires policy review"]),
        )
    if score >= 70:
        return PolicyDecision(
            risk_score=score,
            risk_level="high",
            mode="manual_approval",
            requires_approval=True,
            allowed_roles=("owner",),
            reasons=tuple(reasons or ["High-risk action requires owner approval"]),
        )
    if score >= 30:
        return PolicyDecision(
            risk_score=score,
            risk_level="medium",
            mode="manual_approval",
            requires_approval=True,
            allowed_roles=("owner", "admin"),
            reasons=tuple(reasons or ["Medium-risk action requires workspace review"]),
        )
    if normalized_type in AUTO_APPROVABLE_ACTIONS:
        return PolicyDecision(
            risk_score=score,
            risk_level="low",
            mode="auto_approve",
            requires_approval=False,
            allowed_roles=("system",),
            reasons=tuple(reasons or ["Low-risk reversible action qualifies for automatic approval"]),
        )
    return PolicyDecision(
        risk_score=score,
        risk_level="low",
        mode="manual_approval",
        requires_approval=True,
        allowed_roles=("owner", "admin"),
        reasons=tuple(reasons or ["Action type is not yet approved for automatic execution"]),
    )
