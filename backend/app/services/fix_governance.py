"""Governance helpers for sandbox validation, risk scoring, and execution decisions."""
from dataclasses import dataclass, field


SENSITIVE_PATH_HINTS = ("auth", "secret", "config", ".env", "payment", "billing")


@dataclass
class ValidationCheckResult:
    name: str
    passed: bool
    message: str | None = None
    details: dict | None = None


@dataclass
class SandboxValidationReport:
    passed: bool
    checks: list[ValidationCheckResult]
    failed_checks: list[str] = field(default_factory=list)


@dataclass
class RiskAssessment:
    score: int
    level: str
    reasons: list[str]
    requires_human_approval: bool


def run_sandbox_checks(checks: list[ValidationCheckResult]) -> SandboxValidationReport:
    """Aggregate sandbox checks into a pass/fail report."""
    failed_checks = [check.name for check in checks if not check.passed]
    return SandboxValidationReport(
        passed=len(failed_checks) == 0,
        checks=checks,
        failed_checks=failed_checks,
    )


def assess_fix_risk(
    severity: str | None,
    target_path: str | None,
    changed_files: int,
    action_type: str,
) -> RiskAssessment:
    """Compute risk score for a fix action."""
    score = 0
    reasons: list[str] = []

    severity_score = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    sev = (severity or "medium").lower()
    score += severity_score.get(sev, 2)
    if sev in ("critical", "high"):
        reasons.append("high_severity_issue")

    if changed_files >= 5:
        score += 3
        reasons.append("multi_file_change")
    elif changed_files >= 2:
        score += 1
        reasons.append("multi_file_change")

    path = (target_path or "").lower()
    if any(hint in path for hint in SENSITIVE_PATH_HINTS):
        score += 4
        reasons.append("sensitive_path")

    if action_type not in ("github_pr", "wordpress_update"):
        score += 2
        reasons.append("non_standard_action")

    if score >= 8:
        level = "high"
    elif score >= 5:
        level = "medium"
    else:
        level = "low"

    return RiskAssessment(
        score=score,
        level=level,
        reasons=reasons,
        requires_human_approval=level in ("high", "medium"),
    )


def decide_execution_mode(
    validation_report: SandboxValidationReport,
    risk: RiskAssessment,
    autonomous_enabled: bool,
) -> str:
    """Return auto_execute, needs_approval, or blocked."""
    if not validation_report.passed:
        return "blocked"
    if not autonomous_enabled:
        return "needs_approval"
    if risk.requires_human_approval:
        return "needs_approval"
    return "auto_execute"
