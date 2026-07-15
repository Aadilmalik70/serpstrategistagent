from __future__ import annotations

import base64
import binascii
import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.github_app import (
    GitHubAppInstallation,
    GitHubExecution,
    GitHubRepositoryConnection,
)
from app.models.operator_action import OperatorAction
from app.services.execution_adapters import (
    AdapterResult,
    AdapterSnapshot,
    ExecutionAdapterError,
    ValidationResult,
)
from app.services.github_app_service import GitHubAppError, create_installation_token


PROTECTED_EXACT_PATHS = {
    ".env",
    ".gitmodules",
    "wp-config.php",
}
PROTECTED_PREFIXES = (
    ".git/",
    ".github/",
)
PROTECTED_SUFFIXES = (
    ".key",
    ".pem",
    ".p12",
    ".pfx",
)
SHA_PATTERN = re.compile(r"^[0-9a-f]{40,64}$")
BRANCH_PATTERN = re.compile(r"^[A-Za-z0-9._/-]+$")


class GitHubExecutionError(ExecutionAdapterError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "github_execution_error",
        retryable: bool = False,
    ):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class FileChange:
    path: str
    operation: str
    content: str | None
    expected_sha: str | None


@dataclass(frozen=True)
class ExecutionContext:
    connection: GitHubRepositoryConnection
    installation: GitHubAppInstallation
    repository: str
    base_branch: str
    branch_name: str
    changes: tuple[FileChange, ...]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "SERP-Strategists-Operator",
    }


def _normalize_path(raw: Any) -> str:
    if not isinstance(raw, str):
        raise GitHubExecutionError(
            "Every GitHub file operation requires a repository-relative path",
            code="github_patch_invalid",
        )
    value = raw.strip()
    if (
        not value
        or len(value) > 500
        or value.startswith("/")
        or "\\" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or any(ord(character) < 32 for character in value)
    ):
        raise GitHubExecutionError(
            f"Repository path is not safe: {value[:120] or '<empty>'}",
            code="github_patch_invalid",
        )
    normalized = value.lower()
    basename = normalized.rsplit("/", 1)[-1]
    if (
        basename in PROTECTED_EXACT_PATHS
        or basename.startswith(".env.")
        or normalized.startswith(PROTECTED_PREFIXES)
        or basename.endswith(PROTECTED_SUFFIXES)
    ):
        raise GitHubExecutionError(
            f"Protected repository path cannot be changed: {value}",
            code="github_protected_path",
        )
    return value


def _file_changes(action: OperatorAction) -> tuple[FileChange, ...]:
    settings = get_settings()
    raw_files = (action.proposed_diff or {}).get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise GitHubExecutionError(
            "GitHub execution requires proposed_diff.files with exact create, update, or delete operations",
            code="github_patch_missing",
        )
    if len(raw_files) > settings.github_execution_max_files:
        raise GitHubExecutionError(
            f"GitHub execution is limited to {settings.github_execution_max_files} files per action",
            code="github_patch_too_large",
        )

    changes: list[FileChange] = []
    paths: set[str] = set()
    total_bytes = 0
    for item in raw_files:
        if not isinstance(item, dict):
            raise GitHubExecutionError(
                "Every proposed file operation must be an object",
                code="github_patch_invalid",
            )
        path = _normalize_path(item.get("path"))
        path_key = path.casefold()
        if path_key in paths:
            raise GitHubExecutionError(
                f"The proposed patch contains the same path more than once: {path}",
                code="github_patch_invalid",
            )
        paths.add(path_key)
        operation = str(item.get("operation") or "").strip().lower()
        if operation not in {"create", "update", "delete"}:
            raise GitHubExecutionError(
                f"Unsupported operation for {path}; use create, update, or delete",
                code="github_patch_invalid",
            )
        content = item.get("content")
        if operation == "delete":
            if content not in {None, ""}:
                raise GitHubExecutionError(
                    f"Delete operation for {path} cannot include content",
                    code="github_patch_invalid",
                )
            content = None
        elif not isinstance(content, str):
            raise GitHubExecutionError(
                f"{operation.title()} operation for {path} requires complete UTF-8 text content",
                code="github_patch_invalid",
            )
        if content is not None:
            content_bytes = content.encode("utf-8")
            if len(content_bytes) > settings.github_execution_max_file_bytes:
                raise GitHubExecutionError(
                    f"Proposed content for {path} exceeds the per-file limit",
                    code="github_patch_too_large",
                )
            total_bytes += len(content_bytes)
        expected_sha = item.get("expected_sha")
        if expected_sha is not None:
            expected_sha = str(expected_sha).strip().lower()
            if not SHA_PATTERN.fullmatch(expected_sha):
                raise GitHubExecutionError(
                    f"expected_sha for {path} is not a valid Git object ID",
                    code="github_patch_invalid",
                )
        changes.append(
            FileChange(
                path=path,
                operation=operation,
                content=content,
                expected_sha=expected_sha,
            )
        )
    if total_bytes > settings.github_execution_max_total_bytes:
        raise GitHubExecutionError(
            "The proposed GitHub patch exceeds the total content limit",
            code="github_patch_too_large",
        )
    return tuple(changes)


def _branch_name(action: OperatorAction) -> str:
    settings = get_settings()
    return f"{settings.github_execution_branch_prefix}/action-{str(action.id)[:12]}"


def _base_branch(action: OperatorAction, connection: GitHubRepositoryConnection) -> str:
    requested = str((action.execution_target or {}).get("base_branch") or "").strip()
    branch = requested or str(connection.default_branch or "").strip()
    if (
        not branch
        or len(branch) > 240
        or not BRANCH_PATTERN.fullmatch(branch)
        or branch.startswith("/")
        or branch.endswith("/")
        or ".." in branch
        or "//" in branch
    ):
        raise GitHubExecutionError(
            "The mapped repository does not have a safe base branch",
            code="github_base_branch_invalid",
        )
    return branch


async def _execution_context(
    db: AsyncSession,
    action: OperatorAction,
    *,
    require_patch: bool,
) -> ExecutionContext:
    settings = get_settings()
    if not settings.github_execution_enabled:
        raise GitHubExecutionError(
            "GitHub execution is disabled for this environment",
            code="github_execution_disabled",
        )
    if action.workspace_id is None:
        raise GitHubExecutionError(
            "The action is not attached to a workspace",
            code="github_execution_unauthorized",
        )
    connection = await db.scalar(
        select(GitHubRepositoryConnection).where(
            GitHubRepositoryConnection.site_id == action.site_id,
            GitHubRepositoryConnection.workspace_id == action.workspace_id,
            GitHubRepositoryConnection.status == "active",
        )
    )
    if not connection or not connection.installation_id:
        raise GitHubExecutionError(
            "The action site does not have an active GitHub App repository mapping",
            code="github_repository_not_authorized",
        )
    installation = await db.scalar(
        select(GitHubAppInstallation).where(
            GitHubAppInstallation.id == connection.installation_id,
            GitHubAppInstallation.workspace_id == action.workspace_id,
            GitHubAppInstallation.status == "active",
        )
    )
    if not installation:
        raise GitHubExecutionError(
            "The mapped GitHub App installation is not active",
            code="github_installation_not_found",
        )
    permissions = installation.permissions or {}
    if permissions.get("contents") != "write" or permissions.get("pull_requests") != "write":
        raise GitHubExecutionError(
            "The GitHub App requires Contents: write and Pull requests: write permissions",
            code="github_app_permissions_missing",
        )
    repository = connection.repository_full_name
    if not repository or repository.count("/") != 1:
        raise GitHubExecutionError(
            "The mapped repository name is invalid",
            code="github_repository_not_authorized",
        )
    return ExecutionContext(
        connection=connection,
        installation=installation,
        repository=repository,
        base_branch=_base_branch(action, connection),
        branch_name=_branch_name(action),
        changes=_file_changes(action) if require_patch else tuple(),
    )


class _GitHubProvider:
    def __init__(
        self,
        installation_id: int,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.installation_id = installation_id
        self.client = client
        self._owns_client = client is None
        self._token: str | None = None

    async def __aenter__(self) -> "_GitHubProvider":
        settings = get_settings()
        if self.client is None:
            self.client = httpx.AsyncClient(
                timeout=settings.github_app_timeout_seconds,
                follow_redirects=False,
            )
        try:
            self._token = await create_installation_token(
                self.installation_id,
                client=self.client,
            )
        except GitHubAppError as exc:
            raise GitHubExecutionError(
                str(exc),
                code=exc.code,
                retryable=exc.retryable,
            ) from exc
        return self

    async def __aexit__(self, *_args: object) -> None:
        if self._owns_client and self.client is not None:
            await self.client.aclose()
        self._token = None

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        allow_status: set[int] | None = None,
    ) -> tuple[int, Any]:
        if self.client is None or self._token is None:
            raise RuntimeError("GitHub provider must be entered before use")
        settings = get_settings()
        try:
            response = await self.client.request(
                method,
                f"{settings.github_api_url}{path}",
                headers=_headers(self._token),
                json=json,
                params=params,
            )
        except httpx.RequestError as exc:
            raise GitHubExecutionError(
                "GitHub could not complete the governed repository operation",
                code="github_provider_unavailable",
                retryable=True,
            ) from exc
        allowed = allow_status or set()
        if response.status_code >= 400 and response.status_code not in allowed:
            retryable = response.status_code == 429 or response.status_code >= 500
            if response.status_code in {401, 403}:
                code = "github_app_authorization_failed"
                message = "GitHub rejected the governed operation; verify App and repository permissions"
            elif response.status_code == 404:
                code = "github_provider_resource_missing"
                message = "GitHub could not find a required repository resource"
            elif response.status_code == 409:
                code = "github_repository_conflict"
                message = "GitHub rejected the operation because repository state changed"
            elif response.status_code == 422:
                code = "github_provider_validation_failed"
                message = "GitHub rejected the branch, commit, or draft pull request payload"
            else:
                code = "github_provider_unavailable"
                message = "GitHub could not complete the governed repository operation"
            raise GitHubExecutionError(message, code=code, retryable=retryable)
        if response.status_code == 204:
            return response.status_code, {}
        try:
            return response.status_code, response.json()
        except ValueError as exc:
            raise GitHubExecutionError(
                "GitHub returned an invalid provider response",
                code="github_provider_invalid_response",
                retryable=True,
            ) from exc


def _payload_dict(payload: Any, operation: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise GitHubExecutionError(
            f"GitHub returned an invalid {operation} response",
            code="github_provider_invalid_response",
            retryable=True,
        )
    return payload


def _sha(payload: Any, *, nested_object: bool = False) -> str:
    data = _payload_dict(payload, "Git object")
    if nested_object:
        data = _payload_dict(data.get("object"), "Git reference")
    value = data.get("sha")
    if not isinstance(value, str) or not SHA_PATTERN.fullmatch(value.lower()):
        raise GitHubExecutionError(
            "GitHub returned an invalid object ID",
            code="github_provider_invalid_response",
            retryable=True,
        )
    return value.lower()


async def _ref_sha(provider: _GitHubProvider, repository: str, branch: str) -> str | None:
    encoded = quote(branch, safe="")
    status, payload = await provider.request(
        "GET",
        f"/repos/{repository}/git/ref/heads/{encoded}",
        allow_status={404},
    )
    return None if status == 404 else _sha(payload, nested_object=True)


async def _file_payload(
    provider: _GitHubProvider,
    repository: str,
    path: str,
    ref: str,
) -> dict[str, Any] | None:
    status, payload = await provider.request(
        "GET",
        f"/repos/{repository}/contents/{quote(path, safe='/')}",
        params={"ref": ref},
        allow_status={404},
    )
    if status == 404:
        return None
    data = _payload_dict(payload, "repository content")
    if data.get("type") != "file":
        raise GitHubExecutionError(
            f"The target is not a regular file: {path}",
            code="github_patch_invalid",
        )
    return data


def _decoded_content(payload: dict[str, Any], path: str) -> bytes:
    content = payload.get("content")
    if payload.get("encoding") != "base64" or not isinstance(content, str):
        raise GitHubExecutionError(
            f"GitHub did not return readable file content for {path}",
            code="github_provider_invalid_response",
            retryable=True,
        )
    try:
        return base64.b64decode("".join(content.split()), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise GitHubExecutionError(
            f"GitHub returned invalid base64 file content for {path}",
            code="github_provider_invalid_response",
            retryable=True,
        ) from exc


async def _existing_pull_request(
    provider: _GitHubProvider,
    context: ExecutionContext,
) -> dict[str, Any] | None:
    owner = context.repository.split("/", 1)[0]
    _, payload = await provider.request(
        "GET",
        f"/repos/{context.repository}/pulls",
        params={"state": "open", "head": f"{owner}:{context.branch_name}", "per_page": 10},
    )
    if not isinstance(payload, list):
        raise GitHubExecutionError(
            "GitHub returned an invalid pull request list",
            code="github_provider_invalid_response",
            retryable=True,
        )
    return next((item for item in payload if isinstance(item, dict)), None)


def _pull_request_result(payload: dict[str, Any]) -> dict[str, Any]:
    number = payload.get("number")
    url = payload.get("html_url")
    if not isinstance(number, int) or not isinstance(url, str):
        raise GitHubExecutionError(
            "GitHub returned an invalid draft pull request response",
            code="github_provider_invalid_response",
            retryable=True,
        )
    return {
        "pull_request_number": number,
        "pull_request_url": url,
        "pull_request_state": str(payload.get("state") or "open"),
        "pull_request_draft": bool(payload.get("draft")),
    }


class GitHubExecutionAdapter:
    name = "github"
    available = True
    mutation_enabled = True

    def __init__(self, *, provider_client: httpx.AsyncClient | None = None) -> None:
        self.provider_client = provider_client

    async def preflight(
        self,
        action: OperatorAction,
        *,
        db: AsyncSession,
        operation: str,
    ) -> None:
        context = await _execution_context(
            db,
            action,
            require_patch=operation == "execute",
        )
        if operation == "rollback":
            record = await db.scalar(
                select(GitHubExecution).where(
                    GitHubExecution.action_id == action.id,
                    GitHubExecution.workspace_id == action.workspace_id,
                    GitHubExecution.repository_connection_id == context.connection.id,
                )
            )
            if not record or not record.pull_request_number or not record.commit_sha:
                raise GitHubExecutionError(
                    "No governed GitHub draft pull request is available for rollback",
                    code="github_rollback_unavailable",
                )

    async def capture(
        self,
        action: OperatorAction,
        *,
        phase: str,
        db: AsyncSession,
    ) -> AdapterSnapshot:
        context = await _execution_context(db, action, require_patch=phase == "before")
        async with _GitHubProvider(
            context.installation.installation_id,
            client=self.provider_client,
        ) as provider:
            if phase == "before":
                base_sha = await _ref_sha(provider, context.repository, context.base_branch)
                if not base_sha:
                    raise GitHubExecutionError(
                        "The configured base branch does not exist",
                        code="github_base_branch_missing",
                    )
                files: list[dict[str, Any]] = []
                for change in context.changes:
                    payload = await _file_payload(
                        provider,
                        context.repository,
                        change.path,
                        base_sha,
                    )
                    if change.operation == "create" and payload is not None:
                        raise GitHubExecutionError(
                            f"Create target already exists: {change.path}",
                            code="github_patch_stale",
                        )
                    if change.operation in {"update", "delete"} and payload is None:
                        raise GitHubExecutionError(
                            f"{change.operation.title()} target no longer exists: {change.path}",
                            code="github_patch_stale",
                        )
                    existing_sha = str(payload.get("sha")) if payload else None
                    if change.expected_sha and existing_sha != change.expected_sha:
                        raise GitHubExecutionError(
                            f"Expected object ID no longer matches for {change.path}",
                            code="github_patch_stale",
                        )
                    before_bytes = _decoded_content(payload, change.path) if payload else b""
                    files.append(
                        {
                            "path": change.path,
                            "operation": change.operation,
                            "object_sha": existing_sha,
                            "content_sha256": hashlib.sha256(before_bytes).hexdigest() if payload else None,
                            "content_base64": base64.b64encode(before_bytes).decode("ascii") if payload else None,
                        }
                    )
                return AdapterSnapshot(
                    data={
                        "repository_connection_id": str(context.connection.id),
                        "repository": context.repository,
                        "base_branch": context.base_branch,
                        "base_commit_sha": base_sha,
                        "branch_name": context.branch_name,
                        "files": files,
                    },
                    external_revision=base_sha,
                )

            record = await db.scalar(
                select(GitHubExecution).where(
                    GitHubExecution.action_id == action.id,
                    GitHubExecution.workspace_id == action.workspace_id,
                )
            )
            if not record or not record.commit_sha or not record.pull_request_number:
                raise GitHubExecutionError(
                    "GitHub execution metadata is missing after the provider mutation",
                    code="github_execution_record_missing",
                    retryable=True,
                )
            branch_sha = await _ref_sha(provider, context.repository, record.branch_name)
            _, pull_payload = await provider.request(
                "GET",
                f"/repos/{context.repository}/pulls/{record.pull_request_number}",
            )
            pull = _payload_dict(pull_payload, "pull request")
            files: list[dict[str, Any]] = []
            for change in _file_changes(action):
                payload = await _file_payload(
                    provider,
                    context.repository,
                    change.path,
                    record.branch_name,
                )
                file_bytes = _decoded_content(payload, change.path) if payload else b""
                files.append(
                    {
                        "path": change.path,
                        "operation": change.operation,
                        "present": payload is not None,
                        "object_sha": str(payload.get("sha")) if payload else None,
                        "content_sha256": hashlib.sha256(file_bytes).hexdigest() if payload else None,
                    }
                )
            return AdapterSnapshot(
                data={
                    "repository": context.repository,
                    "base_branch": record.base_branch,
                    "base_commit_sha": record.base_commit_sha,
                    "branch_name": record.branch_name,
                    "branch_commit_sha": branch_sha,
                    "commit_sha": record.commit_sha,
                    "pull_request": _pull_request_result(pull),
                    "files": files,
                },
                external_revision=record.commit_sha,
            )

    async def apply(
        self,
        action: OperatorAction,
        *,
        before: AdapterSnapshot,
        db: AsyncSession,
    ) -> AdapterResult:
        context = await _execution_context(db, action, require_patch=True)
        base_sha = str(before.data.get("base_commit_sha") or "").lower()
        if not SHA_PATTERN.fullmatch(base_sha):
            raise GitHubExecutionError(
                "The immutable before snapshot does not contain a valid base commit",
                code="github_snapshot_invalid",
            )
        existing = await db.scalar(
            select(GitHubExecution).where(
                GitHubExecution.action_id == action.id,
                GitHubExecution.workspace_id == action.workspace_id,
            )
        )
        if existing and existing.commit_sha and existing.pull_request_number and existing.pull_request_url:
            return AdapterResult(
                result={
                    "repository": existing.repository_full_name,
                    "base_branch": existing.base_branch,
                    "base_commit_sha": existing.base_commit_sha,
                    "branch_name": existing.branch_name,
                    "commit_sha": existing.commit_sha,
                    "pull_request_number": existing.pull_request_number,
                    "pull_request_url": existing.pull_request_url,
                    "draft": existing.pull_request_draft,
                    "changed_files": existing.changed_files,
                    "idempotent_replay": True,
                    "site_mutation_applied": False,
                },
                external_revision=existing.commit_sha,
                # A draft PR mutates a review branch, not the deployed site.
                # Search-performance learning must wait for deployment sync.
                mutation_applied=False,
            )

        async with _GitHubProvider(
            context.installation.installation_id,
            client=self.provider_client,
        ) as provider:
            current_base_sha = await _ref_sha(provider, context.repository, context.base_branch)
            if current_base_sha != base_sha:
                raise GitHubExecutionError(
                    "The base branch changed after approval; refresh the patch and approve a new action",
                    code="github_base_changed",
                )

            branch_sha = await _ref_sha(provider, context.repository, context.branch_name)
            if branch_sha:
                _, commit_payload = await provider.request(
                    "GET",
                    f"/repos/{context.repository}/git/commits/{branch_sha}",
                )
                commit = _payload_dict(commit_payload, "commit")
                message = str(commit.get("message") or "")
                parents = commit.get("parents") if isinstance(commit.get("parents"), list) else []
                parent_shas = {
                    str(item.get("sha"))
                    for item in parents
                    if isinstance(item, dict) and item.get("sha")
                }
                if f"SERP-Operator-Action: {action.id}" not in message or base_sha not in parent_shas:
                    raise GitHubExecutionError(
                        "The deterministic action branch already exists with unrelated commits",
                        code="github_branch_conflict",
                    )
                commit_sha = branch_sha
            else:
                _, base_commit_payload = await provider.request(
                    "GET",
                    f"/repos/{context.repository}/git/commits/{base_sha}",
                )
                base_commit = _payload_dict(base_commit_payload, "base commit")
                base_tree_sha = _sha(base_commit.get("tree"))
                before_files = {
                    str(item.get("path")): item
                    for item in before.data.get("files", [])
                    if isinstance(item, dict) and item.get("path")
                }
                tree_entries: list[dict[str, Any]] = []
                changed_files: list[dict[str, str]] = []
                for change in context.changes:
                    if change.operation == "delete":
                        tree_entries.append(
                            {"path": change.path, "mode": "100644", "type": "blob", "sha": None}
                        )
                    else:
                        proposed_bytes = (change.content or "").encode("utf-8")
                        previous_b64 = before_files.get(change.path, {}).get("content_base64")
                        previous_bytes = (
                            base64.b64decode(previous_b64)
                            if isinstance(previous_b64, str) and previous_b64
                            else None
                        )
                        if change.operation == "update" and previous_bytes == proposed_bytes:
                            raise GitHubExecutionError(
                                f"The approved update does not change repository content: {change.path}",
                                code="github_patch_no_changes",
                            )
                        _, blob_payload = await provider.request(
                            "POST",
                            f"/repos/{context.repository}/git/blobs",
                            json={
                                "content": base64.b64encode(proposed_bytes).decode("ascii"),
                                "encoding": "base64",
                            },
                        )
                        tree_entries.append(
                            {
                                "path": change.path,
                                "mode": "100644",
                                "type": "blob",
                                "sha": _sha(blob_payload),
                            }
                        )
                    changed_files.append({"path": change.path, "operation": change.operation})
                if not tree_entries:
                    raise GitHubExecutionError(
                        "The approved GitHub patch does not change repository content",
                        code="github_patch_no_changes",
                    )
                _, tree_payload = await provider.request(
                    "POST",
                    f"/repos/{context.repository}/git/trees",
                    json={"base_tree": base_tree_sha, "tree": tree_entries},
                )
                tree_sha = _sha(tree_payload)
                if tree_sha == base_tree_sha:
                    raise GitHubExecutionError(
                        "The approved GitHub patch does not change repository content",
                        code="github_patch_no_changes",
                    )
                commit_message = str((action.proposed_diff or {}).get("commit_message") or action.title).strip()
                commit_message = commit_message[:180] or "Apply governed SEO operator action"
                commit_message = f"{commit_message}\n\nSERP-Operator-Action: {action.id}"
                _, created_commit = await provider.request(
                    "POST",
                    f"/repos/{context.repository}/git/commits",
                    json={"message": commit_message, "tree": tree_sha, "parents": [base_sha]},
                )
                commit_sha = _sha(created_commit)
                status_code, _ = await provider.request(
                    "POST",
                    f"/repos/{context.repository}/git/refs",
                    json={"ref": f"refs/heads/{context.branch_name}", "sha": commit_sha},
                    allow_status={422},
                )
                if status_code == 422:
                    raced_sha = await _ref_sha(provider, context.repository, context.branch_name)
                    if raced_sha != commit_sha:
                        raise GitHubExecutionError(
                            "The deterministic action branch was created concurrently with different content",
                            code="github_branch_conflict",
                        )

            pull = await _existing_pull_request(provider, context)
            if pull is None:
                file_lines = "\n".join(
                    f"- `{change.operation}` `{change.path}`" for change in context.changes
                )
                body = (
                    "## Governed operator action\n\n"
                    f"Action: `{action.id}`\n\n"
                    "This draft pull request was created from an explicitly approved, immutable file plan. "
                    "It must be reviewed and merged by a human.\n\n"
                    "### Files\n"
                    f"{file_lines}\n\n"
                    "### Safety\n"
                    "- protected paths were rejected before mutation\n"
                    "- the base commit and target file state were snapshotted\n"
                    "- autonomous merge and force-push are disabled\n"
                )
                _, pull_payload = await provider.request(
                    "POST",
                    f"/repos/{context.repository}/pulls",
                    json={
                        "title": action.title[:256],
                        "head": context.branch_name,
                        "base": context.base_branch,
                        "body": body,
                        "draft": True,
                        "maintainer_can_modify": False,
                    },
                )
                pull = _payload_dict(pull_payload, "draft pull request")
            pull_result = _pull_request_result(pull)
            if not pull_result["pull_request_draft"]:
                raise GitHubExecutionError(
                    "GitHub did not create a draft pull request",
                    code="github_pr_not_draft",
                )

        changed_files = [
            {"path": change.path, "operation": change.operation}
            for change in context.changes
        ]
        record = existing or GitHubExecution(
            workspace_id=action.workspace_id,
            site_id=action.site_id,
            action_id=action.id,
            repository_connection_id=context.connection.id,
            repository_full_name=context.repository,
            base_branch=context.base_branch,
            base_commit_sha=base_sha,
            branch_name=context.branch_name,
        )
        record.commit_sha = commit_sha
        record.pull_request_number = pull_result["pull_request_number"]
        record.pull_request_url = pull_result["pull_request_url"]
        record.pull_request_state = pull_result["pull_request_state"]
        record.pull_request_draft = pull_result["pull_request_draft"]
        record.status = "draft_pr_open"
        record.changed_files = changed_files
        db.add(record)
        await db.flush()
        return AdapterResult(
            result={
                "repository": context.repository,
                "base_branch": context.base_branch,
                "base_commit_sha": base_sha,
                "branch_name": context.branch_name,
                "commit_sha": commit_sha,
                **pull_result,
                "draft": pull_result["pull_request_draft"],
                "changed_files": changed_files,
                "idempotent_replay": branch_sha is not None,
                "site_mutation_applied": False,
            },
            external_revision=commit_sha,
            mutation_applied=False,
        )

    async def validate(
        self,
        action: OperatorAction,
        *,
        before: AdapterSnapshot,
        execution_result: dict[str, Any],
        db: AsyncSession,
    ) -> ValidationResult:
        del before, execution_result
        context = await _execution_context(db, action, require_patch=False)
        record = await db.scalar(
            select(GitHubExecution).where(
                GitHubExecution.action_id == action.id,
                GitHubExecution.workspace_id == action.workspace_id,
            )
        )
        if not record or not record.commit_sha or not record.pull_request_number:
            raise GitHubExecutionError(
                "GitHub execution metadata is missing",
                code="github_execution_record_missing",
                retryable=True,
            )
        async with _GitHubProvider(
            context.installation.installation_id,
            client=self.provider_client,
        ) as provider:
            branch_sha = await _ref_sha(provider, context.repository, record.branch_name)
            _, pull_payload = await provider.request(
                "GET",
                f"/repos/{context.repository}/pulls/{record.pull_request_number}",
            )
        pull = _payload_dict(pull_payload, "pull request")
        head = pull.get("head") if isinstance(pull.get("head"), dict) else {}
        base = pull.get("base") if isinstance(pull.get("base"), dict) else {}
        checks = [
            {"label": "Draft pull request remains open", "passed": pull.get("state") == "open" and bool(pull.get("draft"))},
            {"label": "Branch points to the governed commit", "passed": branch_sha == record.commit_sha},
            {"label": "Pull request head matches the governed commit", "passed": head.get("sha") == record.commit_sha},
            {"label": "Pull request base matches the approved base branch", "passed": base.get("ref") == record.base_branch},
            {"label": "No autonomous merge occurred", "passed": not bool(pull.get("merged")) and pull.get("merged_at") is None},
        ]
        passed = all(bool(item["passed"]) for item in checks)
        record.validation = {"passed": passed, "checks": checks, "validated_at": _now().isoformat()}
        record.pull_request_state = str(pull.get("state") or record.pull_request_state or "unknown")
        record.pull_request_draft = bool(pull.get("draft"))
        record.status = "validated" if passed else "validation_failed"
        if passed:
            record.completed_at = _now()
        await db.flush()
        return ValidationResult(
            passed=passed,
            checks=checks,
            summary="GitHub draft pull request validation passed" if passed else "GitHub draft pull request validation failed",
        )

    async def rollback(
        self,
        action: OperatorAction,
        *,
        before: AdapterSnapshot,
        db: AsyncSession,
    ) -> AdapterResult:
        del before
        context = await _execution_context(db, action, require_patch=False)
        record = await db.scalar(
            select(GitHubExecution).where(
                GitHubExecution.action_id == action.id,
                GitHubExecution.workspace_id == action.workspace_id,
            )
        )
        if not record or not record.commit_sha or not record.pull_request_number:
            raise GitHubExecutionError(
                "No governed GitHub draft pull request is available for rollback",
                code="github_rollback_unavailable",
            )
        async with _GitHubProvider(
            context.installation.installation_id,
            client=self.provider_client,
        ) as provider:
            _, pull_payload = await provider.request(
                "GET",
                f"/repos/{context.repository}/pulls/{record.pull_request_number}",
            )
            pull = _payload_dict(pull_payload, "pull request")
            if pull.get("merged") or pull.get("merged_at"):
                raise GitHubExecutionError(
                    "The pull request was merged; provider rollback requires a separately reviewed revert action",
                    code="github_rollback_requires_revert",
                )
            if pull.get("state") == "open":
                await provider.request(
                    "PATCH",
                    f"/repos/{context.repository}/pulls/{record.pull_request_number}",
                    json={"state": "closed"},
                )
            branch_sha = await _ref_sha(provider, context.repository, record.branch_name)
            if branch_sha and branch_sha != record.commit_sha:
                raise GitHubExecutionError(
                    "The action branch contains newer commits and cannot be deleted automatically",
                    code="github_rollback_branch_advanced",
                )
            if branch_sha:
                await provider.request(
                    "DELETE",
                    f"/repos/{context.repository}/git/refs/heads/{quote(record.branch_name, safe='')}",
                )
        rollback_result = {
            "pull_request_number": record.pull_request_number,
            "pull_request_url": record.pull_request_url,
            "pull_request_closed": True,
            "branch_deleted": bool(branch_sha),
            "default_branch_unchanged": True,
        }
        record.status = "rolled_back"
        record.pull_request_state = "closed"
        record.rollback = {**rollback_result, "rolled_back_at": _now().isoformat()}
        record.rolled_back_at = _now()
        await db.flush()
        return AdapterResult(
            result=rollback_result,
            external_revision=record.base_commit_sha,
            mutation_applied=True,
        )
