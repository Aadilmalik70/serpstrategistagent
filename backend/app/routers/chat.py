"""Chat API — conversational interface to the SEO agent."""

from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies.workspace import WorkspaceContext, get_current_workspace
from app.services.agent_chat import get_or_create_session
from app.services.site_service import get_site_by_id

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatMessage(BaseModel):
    message: str


class ChatResponse(BaseModel):
    response: str
    timestamp: str


class ChatHistory(BaseModel):
    messages: list[dict]


async def _authorize_site(
    db: AsyncSession,
    context: WorkspaceContext,
    site_id: uuid.UUID,
) -> None:
    if not await get_site_by_id(db, site_id, context.workspace.id):
        raise HTTPException(status_code=404, detail="Site not found")


@router.post("/{site_id}", response_model=ChatResponse)
async def send_message(
    site_id: uuid.UUID,
    body: ChatMessage,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    await _authorize_site(db, context, site_id)
    session = get_or_create_session(site_id)

    try:
        response = await session.chat(body.message, db)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return ChatResponse(
        response=response,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/{site_id}/history", response_model=ChatHistory)
async def get_history(
    site_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    await _authorize_site(db, context, site_id)
    session = get_or_create_session(site_id)
    return ChatHistory(messages=session.messages)


@router.delete("/{site_id}/history")
async def clear_history(
    site_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    await _authorize_site(db, context, site_id)
    session = get_or_create_session(site_id)
    session.messages = []
    session._repo_tree = None
    return {"status": "cleared"}
