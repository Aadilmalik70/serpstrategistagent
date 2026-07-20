import base64
import json
from types import SimpleNamespace
import uuid

import httpx
import pytest

from app.config import get_settings
from app.services.ai_gateway import AIGatewayResult
from app.services import github_patch_planner as planner
from app.services.technical_finding_service import _action_data


class _ScalarSession:
    def __init__(self, *values):
        self.values = list(values)

    async def scalar(self, _query):
        return self.values.pop(0)


def _finding() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        site_id=uuid.uuid4(),
        finding_type="images_missing_alt",
        title="Images are missing alternative text",
        description="The homepage has an image without alt text.",
        recommendation="Add concise contextual alternative text.",
        affected_url="/",
        affected_urls=["/"],
        evidence=[{"type": "crawl_observation", "images_without_alt": 1}],
    )


def test_repository_candidate_ranking_maps_nextjs_routes_without_guessing() -> None:
    paths = [
        "backend/app/main.py",
        "frontend/app/page.tsx",
        "frontend/app/about/page.tsx",
        "frontend/public/landing.html",
    ]
    assert planner.select_repository_candidate(paths, "/") == "frontend/app/page.tsx"
    assert planner.select_repository_candidate(paths, "/about") == "frontend/app/about/page.tsx"
    assert planner.select_repository_candidate(
        ["frontend/app/page.tsx", "website/app/page.tsx"],
        "/",
    ) is None


def test_local_import_resolution_stays_inside_repository_source_paths() -> None:
    source = (
        'import { Hero } from "@/components/hero";\n'
        'import Footer from "../components/footer";\n'
        'import packageValue from "external-package";\n'
    )
    assert planner.resolve_local_imports(
        source_path="app/page.tsx",
        source=source,
        repository_paths={
            "components/hero.tsx",
            "components/footer/index.tsx",
            "node_modules/external-package/index.js",
        },
    ) == ["components/hero.tsx", "components/footer/index.tsx"]


def test_generated_alt_patch_requires_a_meaningful_improvement() -> None:
    before = 'export default () => <Image src="/hero.png" />;\n'
    after = 'export default () => <Image src="/hero.png" alt="AI growth operator dashboard" />;\n'
    assert planner.validate_generated_patch(
        finding_type="images_missing_alt",
        before=before,
        after=after,
    ) == 2

    with pytest.raises(planner.GitHubPatchPlanningError) as empty_alt:
        planner.validate_generated_patch(
            finding_type="images_missing_alt",
            before=before,
            after='export default () => <Image src="/hero.png" alt="" />;\n',
        )
    assert empty_alt.value.code == "github_planner_postcondition_failed"

    with pytest.raises(planner.GitHubPatchPlanningError) as partial_alt:
        planner.validate_generated_patch(
            finding_type="images_missing_alt",
            before='<img src="one.png"><img src="two.png">\n',
            after='<img src="one.png" alt="First product view"><img src="two.png">\n',
        )
    assert partial_alt.value.code == "github_planner_postcondition_failed"


def test_generated_title_patch_must_resolve_the_detector_threshold() -> None:
    before = 'export const metadata = { title: "Tiny" };\n'
    after = 'export const metadata = { title: "A descriptive technical SEO operations title" };\n'
    assert planner.validate_generated_patch(
        finding_type="title_too_short",
        before=before,
        after=after,
    ) == 2

    with pytest.raises(planner.GitHubPatchPlanningError) as unchanged_defect:
        planner.validate_generated_patch(
            finding_type="title_too_short",
            before=before,
            after='export const metadata = { title: "Tiny", description: "Added only a description" };\n',
        )
    assert unchanged_defect.value.code == "github_planner_postcondition_failed"


def test_exact_patch_idempotency_is_scoped_to_repository_mapping() -> None:
    finding = SimpleNamespace(
        id=uuid.uuid4(),
        site_id=uuid.uuid4(),
        finding_type="missing_h1",
        fingerprint="f" * 64,
        regression_count=0,
        category="technical",
        title="Missing H1",
        description="The page has no H1.",
        recommendation="Add one descriptive H1.",
        affected_url="/",
        affected_urls=["/"],
        evidence=[{"type": "crawl_observation"}],
        impact_score=70,
        confidence_score=99,
        effort_score=25,
        detector_version="first-party-v1",
        status="open",
        meta={"action": {"action_type": "content_refresh_draft", "risk_score": 10}},
    )

    def patch_plan(
        connection_id: uuid.UUID,
        *,
        repository: str = "operator/site",
        base_branch: str = "main",
        source_path: str = "app/page.tsx",
    ) -> planner.RepositoryPatchPlan:
        return planner.RepositoryPatchPlan(
            status="ready",
            reason_code="exact_patch_ready",
            reason="Exact patch ready.",
            execution_target={
                "adapter": "github",
                "repository_connection_id": str(connection_id),
                "repository": repository,
                "base_branch": base_branch,
                "source_path": source_path,
            },
            proposed_diff={
                "planner": {"status": "ready", "expected_sha": "a" * 40},
                "files": [{"path": "app/page.tsx", "content": "<h1>Home</h1>"}],
            },
            rollback_plan={"required": True},
        )

    connection_id = uuid.uuid4()
    first = _action_data(finding, patch_plan(connection_id))
    remapped = _action_data(finding, patch_plan(uuid.uuid4()))
    branch_changed = _action_data(
        finding,
        patch_plan(connection_id, base_branch="production"),
    )
    path_changed = _action_data(
        finding,
        patch_plan(connection_id, source_path="app/home/page.tsx"),
    )
    assert first is not None and remapped is not None
    assert branch_changed is not None and path_changed is not None
    assert len(
        {
            first.idempotency_key,
            remapped.idempotency_key,
            branch_changed.idempotency_key,
            path_changed.idempotency_key,
        }
    ) == 4
    assert len(first.idempotency_key or "") <= 128


@pytest.mark.asyncio
async def test_planner_builds_exact_reviewable_patch_without_persisting_token(monkeypatch) -> None:
    settings = get_settings()
    previous_enabled = settings.github_patch_planning_enabled
    settings.github_patch_planning_enabled = True
    finding = _finding()
    route_source = (
        'import { Landing } from "@/components/landing";\n'
        'export default () => <Landing />;\n'
    )
    section_source = (
        'import { Hero } from "./hero";\n'
        'export const Landing = () => <Hero />;\n'
    )
    source = 'export const Hero = () => <Image src="/hero.png" />;\n'
    generated = 'export default () => <Image src="/hero.png" alt="AI growth operator dashboard" />;\n'
    expected_sha = "a" * 40
    connection = SimpleNamespace(
        id=uuid.uuid4(),
        installation_id=uuid.uuid4(),
        repository_full_name="operator/site",
        default_branch="main",
    )
    installation = SimpleNamespace(
        installation_id=78123,
        permissions={"contents": "write", "pull_requests": "write"},
    )
    db = _ScalarSession(connection, installation)

    async def fake_installation_token(_installation_id: int, **_kwargs) -> str:
        return "ephemeral-planner-token"

    async def fake_ai(**kwargs) -> AIGatewayResult:
        prompt = kwargs["messages"][1]["content"]
        assert "BEGIN UNTRUSTED SOURCE" in prompt
        assert source.strip() in prompt
        assert route_source.strip() not in prompt
        return AIGatewayResult(
            data={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "can_patch": True,
                                    "content": generated,
                                    "summary": "Add contextual hero image alternative text",
                                    "validation_notes": ["Review the inferred description"],
                                }
                            )
                        }
                    }
                ]
            },
            model="test-model",
            endpoint="chat_completions",
            workspace_id=kwargs["workspace_id"],
            site_id=kwargs["site_id"],
            purpose=kwargs["purpose"],
            usage={},
        )

    async def provider_handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer ephemeral-planner-token"
        if request.url.path.endswith("/git/trees/main"):
            return httpx.Response(
                200,
                json={
                    "truncated": False,
                    "tree": [
                        {"type": "blob", "path": "backend/app/main.py"},
                        {"type": "blob", "path": "frontend/app/page.tsx"},
                        {"type": "blob", "path": "frontend/components/landing.tsx"},
                        {"type": "blob", "path": "frontend/components/hero.tsx"},
                    ],
                },
            )
        if request.url.path.endswith("/contents/frontend/app/page.tsx"):
            return httpx.Response(
                200,
                json={
                    "type": "file",
                    "sha": expected_sha,
                    "encoding": "base64",
                    "content": base64.b64encode(route_source.encode()).decode(),
                },
            )
        if request.url.path.endswith("/contents/frontend/components/hero.tsx"):
            return httpx.Response(
                200,
                json={
                    "type": "file",
                    "sha": expected_sha,
                    "encoding": "base64",
                    "content": base64.b64encode(source.encode()).decode(),
                },
            )
        if request.url.path.endswith("/contents/frontend/components/landing.tsx"):
            return httpx.Response(
                200,
                json={
                    "type": "file",
                    "sha": "c" * 40,
                    "encoding": "base64",
                    "content": base64.b64encode(section_source.encode()).decode(),
                },
            )
        raise AssertionError(f"Unexpected provider request: {request.method} {request.url}")

    monkeypatch.setattr(planner, "create_installation_token", fake_installation_token)
    monkeypatch.setattr(planner, "request_ai", fake_ai)
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider_handler)) as client:
            result = await planner.plan_patch_for_finding(
                db,  # type: ignore[arg-type]
                workspace_id=uuid.uuid4(),
                finding=finding,  # type: ignore[arg-type]
                provider_client=client,
            )
    finally:
        settings.github_patch_planning_enabled = previous_enabled

    assert result.ready is True
    assert result.execution_target["adapter"] == "github"
    assert result.execution_target["source_path"] == "frontend/components/hero.tsx"
    assert result.proposed_diff["mode"] == "exact_github_patch"
    assert result.proposed_diff["files"] == [
        {
            "path": "frontend/components/hero.tsx",
            "operation": "update",
            "content": generated,
            "expected_sha": expected_sha,
        }
    ]
    assert result.proposed_diff["planner"]["changed_lines"] == 2
    assert "ephemeral-planner-token" not in repr(result)
