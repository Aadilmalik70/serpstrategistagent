import base64
import json
from types import SimpleNamespace
import uuid

import httpx
import pytest

from app.config import get_settings
from app.services.ai_gateway import AIGatewayResult
from app.services import github_patch_planner as planner


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


@pytest.mark.asyncio
async def test_planner_builds_exact_reviewable_patch_without_persisting_token(monkeypatch) -> None:
    settings = get_settings()
    previous_enabled = settings.github_patch_planning_enabled
    settings.github_patch_planning_enabled = True
    finding = _finding()
    route_source = (
        'import { Hero } from "@/components/hero";\n'
        'export default () => <Hero />;\n'
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
