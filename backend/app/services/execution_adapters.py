from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.models.operator_action import OperatorAction


class ExecutionAdapterError(RuntimeError):
    code = "adapter_error"
    retryable = False


class ExecutionAdapterUnavailable(ExecutionAdapterError):
    code = "adapter_unavailable"


class ExecutionValidationFailed(ExecutionAdapterError):
    code = "validation_failed"


@dataclass(frozen=True)
class AdapterSnapshot:
    data: dict[str, Any]
    external_revision: str | None = None


@dataclass(frozen=True)
class AdapterResult:
    result: dict[str, Any]
    external_revision: str | None = None


@dataclass(frozen=True)
class ValidationResult:
    passed: bool
    checks: list[dict[str, Any]]
    summary: str


class ExecutionAdapter(Protocol):
    name: str
    available: bool
    mutation_enabled: bool

    async def capture(self, action: OperatorAction, *, phase: str) -> AdapterSnapshot:
        ...

    async def apply(self, action: OperatorAction, *, before: AdapterSnapshot) -> AdapterResult:
        ...

    async def validate(
        self,
        action: OperatorAction,
        *,
        before: AdapterSnapshot,
        execution_result: dict[str, Any],
    ) -> ValidationResult:
        ...

    async def rollback(
        self,
        action: OperatorAction,
        *,
        before: AdapterSnapshot,
    ) -> AdapterResult:
        ...


class SimulationExecutionAdapter:
    """Non-mutating adapter used to verify orchestration safely."""

    name = "simulation"
    available = True
    mutation_enabled = False

    async def capture(self, action: OperatorAction, *, phase: str) -> AdapterSnapshot:
        return AdapterSnapshot(
            data={
                "phase": phase,
                "action_id": str(action.id),
                "action_version": action.version,
                "target": action.execution_target or {},
                "proposed_diff": action.proposed_diff or {},
                "simulated": True,
            },
            external_revision=f"simulation:{action.id}:{action.version}:{phase}",
        )

    async def apply(self, action: OperatorAction, *, before: AdapterSnapshot) -> AdapterResult:
        return AdapterResult(
            result={
                "mode": "simulation",
                "mutated": False,
                "target": action.execution_target or {},
                "proposed_diff": action.proposed_diff or {},
                "before_revision": before.external_revision,
            },
            external_revision=f"simulation:{action.id}:{action.version}:applied",
        )

    async def validate(
        self,
        action: OperatorAction,
        *,
        before: AdapterSnapshot,
        execution_result: dict[str, Any],
    ) -> ValidationResult:
        del before
        checks: list[dict[str, Any]] = []
        for item in action.validation_checklist or []:
            label = item if isinstance(item, str) else str(item.get("label") or item.get("check") or "Validation check")
            checks.append({"label": label, "passed": True, "mode": "simulation"})
        if not checks:
            checks.append({"label": "Execution result recorded", "passed": bool(execution_result), "mode": "simulation"})
        passed = all(bool(item["passed"]) for item in checks)
        return ValidationResult(
            passed=passed,
            checks=checks,
            summary="Simulation validation passed" if passed else "Simulation validation failed",
        )

    async def rollback(
        self,
        action: OperatorAction,
        *,
        before: AdapterSnapshot,
    ) -> AdapterResult:
        return AdapterResult(
            result={
                "mode": "simulation",
                "mutated": False,
                "restored_snapshot": before.data,
            },
            external_revision=f"simulation:{action.id}:{action.version}:rolled-back",
        )


class DisabledExecutionAdapter:
    available = False
    mutation_enabled = False

    def __init__(self, name: str):
        self.name = name

    def _raise(self) -> None:
        raise ExecutionAdapterUnavailable(
            f"The {self.name} execution adapter is installed as a contract only and is not enabled for mutations."
        )

    async def capture(self, action: OperatorAction, *, phase: str) -> AdapterSnapshot:
        del action, phase
        self._raise()

    async def apply(self, action: OperatorAction, *, before: AdapterSnapshot) -> AdapterResult:
        del action, before
        self._raise()

    async def validate(
        self,
        action: OperatorAction,
        *,
        before: AdapterSnapshot,
        execution_result: dict[str, Any],
    ) -> ValidationResult:
        del action, before, execution_result
        self._raise()

    async def rollback(
        self,
        action: OperatorAction,
        *,
        before: AdapterSnapshot,
    ) -> AdapterResult:
        del action, before
        self._raise()


def get_execution_adapter(name: str) -> ExecutionAdapter:
    normalized = (name or "").strip().lower()
    if normalized == "simulation":
        return SimulationExecutionAdapter()
    if normalized in {"github", "wordpress"}:
        raise ExecutionAdapterUnavailable(
            f"The {normalized} execution adapter is installed as a contract only and is not enabled for mutations."
        )
    raise ExecutionAdapterUnavailable(f"Unknown execution adapter: {normalized or 'not specified'}")
