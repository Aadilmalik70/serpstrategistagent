from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.config import get_settings
from app.dependencies.workspace import WorkspaceContext, get_current_workspace, require_workspace_role
from app.services.ai_gateway import AIGatewayError, request_ai
from app.services.serpapi_service import SerpApiError, search_serp


router = APIRouter(prefix="/internal/staging", tags=["staging"])


@router.post("/provider-smoke")
async def provider_smoke(
    context: WorkspaceContext = Depends(get_current_workspace),
) -> dict[str, Any]:
    settings = get_settings()
    if settings.app_env.lower() != "staging":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    require_workspace_role(context, "owner", "admin")

    ai_result: dict[str, Any]
    try:
        result = await request_ai(
            workspace_id=context.workspace.id,
            purpose="staging_provider_smoke",
            messages=[
                {
                    "role": "user",
                    "content": "Reply with exactly: SERP Strategists AI gateway works",
                }
            ],
        )
        choices = result.data.get("choices") if isinstance(result.data, dict) else None
        ai_result = {
            "ok": isinstance(choices, list) and len(choices) > 0,
            "model": result.model,
            "endpoint": result.endpoint,
            "usage_present": bool(result.usage),
        }
    except AIGatewayError as exc:
        ai_result = {
            "ok": False,
            "error": str(exc),
            "status_code": exc.status_code,
            "retryable": exc.retryable,
        }

    serp_result: dict[str, Any]
    try:
        result = await search_serp(
            workspace_id=context.workspace.id,
            query="SERP Strategists",
            purpose="staging_provider_smoke",
            num=1,
        )
        provider_error = result.data.get("error") if isinstance(result.data, dict) else None
        search_status = (
            result.data.get("search_metadata", {}).get("status")
            if isinstance(result.data.get("search_metadata"), dict)
            else None
        )
        organic_results = result.data.get("organic_results")
        serp_result = {
            "ok": not provider_error and search_status not in {"Error", "Failed"},
            "engine": result.engine,
            "search_status": search_status,
            "organic_result_count": len(organic_results) if isinstance(organic_results, list) else 0,
        }
        if provider_error:
            serp_result["error"] = str(provider_error)
    except SerpApiError as exc:
        serp_result = {
            "ok": False,
            "error": str(exc),
            "status_code": exc.status_code,
            "retryable": exc.retryable,
        }

    return {
        "environment": settings.app_env,
        "workspace_id": str(context.workspace.id),
        "ai": ai_result,
        "serpapi": serp_result,
        "all_ok": bool(ai_result.get("ok") and serp_result.get("ok")),
    }
