from datetime import datetime
from typing import Any
import uuid

from pydantic import BaseModel, Field


class ExecutionEnqueueRequest(BaseModel):
    expected_version: int = Field(ge=1)


class ExecutionJobResponse(BaseModel):
    id: uuid.UUID
    action_id: uuid.UUID
    workspace_id: uuid.UUID
    site_id: uuid.UUID
    parent_job_id: uuid.UUID | None
    job_type: str
    adapter: str
    status: str
    priority: int
    attempt_count: int
    max_attempts: int
    idempotency_key: str
    payload: dict[str, Any]
    result: dict[str, Any]
    error_code: str | None
    error_message: str | None
    run_after: datetime
    lease_owner: str | None
    lease_expires_at: datetime | None
    cancellation_requested: bool
    created_by_user_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class ExecutionAttemptResponse(BaseModel):
    id: uuid.UUID
    job_id: uuid.UUID
    attempt_number: int
    worker_id: str
    status: str
    result: dict[str, Any]
    error_code: str | None
    error_message: str | None
    started_at: datetime
    completed_at: datetime | None


class ExecutionSnapshotResponse(BaseModel):
    id: uuid.UUID
    action_id: uuid.UUID
    job_id: uuid.UUID
    workspace_id: uuid.UUID
    site_id: uuid.UUID
    snapshot_type: str
    adapter: str
    external_revision: str | None
    checksum: str
    data: dict[str, Any]
    created_at: datetime


class ExecutionJobDetailResponse(ExecutionJobResponse):
    attempts: list[ExecutionAttemptResponse]
    snapshots: list[ExecutionSnapshotResponse]
