"""Chat API — conversational interface to the SEO agent."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.agent_chat import get_or_create_session

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatMessage(BaseModel):
    message: str


class ChatResponse(BaseModel):
    response: str
    timestamp: str


class ChatHistory(BaseModel):
    messages: list[dict]


@router.post("/{site_id}", response_model=ChatResponse)
async def send_message(
    site_id: uuid.UUID,
    body: ChatMessage,
    db: AsyncSession = Depends(get_db),
):
    """Send a message to the SEO agent and get a response."""
    session = get_or_create_session(site_id)

    try:
        response = await session.chat(body.message, db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return ChatResponse(
        response=response,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/{site_id}/history", response_model=ChatHistory)
async def get_history(site_id: uuid.UUID):
    """Get chat history for a site."""
    session = get_or_create_session(site_id)
    return ChatHistory(messages=session.messages)


@router.delete("/{site_id}/history")
async def clear_history(site_id: uuid.UUID):
    """Clear chat history (start fresh conversation)."""
    session = get_or_create_session(site_id)
    session.messages = []
    session._repo_tree = None
    return {"status": "cleared"}
