"""Compatibility import for legacy planner and executor modules.

Phase 3 normalizes the former FixAction record into OperatorAction. Existing
modules may keep importing FixAction while they migrate to the governed action
service, but all records now use the operator_actions table and lifecycle.
"""

from app.models.operator_action import OperatorAction

FixAction = OperatorAction

__all__ = ["FixAction"]
