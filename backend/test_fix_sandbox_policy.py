from app.services.fix_governance import (
    ValidationCheckResult,
    SandboxValidationReport,
    assess_fix_risk,
    decide_execution_mode,
    run_sandbox_checks,
)


def test_assess_fix_risk_marks_high_for_sensitive_paths_and_large_changes():
    score = assess_fix_risk(
        severity="critical",
        target_path="app/auth/secrets.py",
        changed_files=6,
        action_type="github_pr",
    )
    assert score.level == "high"
    assert score.requires_human_approval is True
    assert "sensitive_path" in score.reasons


def test_decide_execution_mode_auto_for_low_risk_when_autonomous_enabled():
    report = SandboxValidationReport(
        passed=True,
        checks=[
            ValidationCheckResult(name="build_install", passed=True),
            ValidationCheckResult(name="smoke_test", passed=True),
            ValidationCheckResult(name="seo_checks", passed=True),
        ],
    )
    risk = assess_fix_risk(
        severity="low",
        target_path="app/page.tsx",
        changed_files=1,
        action_type="github_pr",
    )
    mode = decide_execution_mode(
        validation_report=report,
        risk=risk,
        autonomous_enabled=True,
    )
    assert mode == "auto_execute"


def test_run_sandbox_checks_fails_when_any_required_check_fails():
    checks = [
        ValidationCheckResult(name="build_install", passed=True),
        ValidationCheckResult(name="smoke_test", passed=False, message="Failed health endpoint"),
        ValidationCheckResult(name="seo_checks", passed=True),
    ]

    report = run_sandbox_checks(checks)
    assert report.passed is False
    assert report.failed_checks == ["smoke_test"]
