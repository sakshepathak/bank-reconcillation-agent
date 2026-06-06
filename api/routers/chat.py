"""Chat endpoint — org-scoped bookkeeping assistant over the live DB."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlmodel import Session

from api.deps import get_db, get_current_org_id
from engine.assistant.agent import run_assistant

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatTurn(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatTurn] = Field(default_factory=list)


class ChatResponse(BaseModel):
    reply: str
    tools_used: list[str] = Field(default_factory=list)


@router.post("/", response_model=ChatResponse)
def chat(
    body: ChatRequest,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    # Only pass clean user/assistant turns into the agent's context.
    history = [
        {"role": t.role, "content": t.content}
        for t in body.history
        if t.role in ("user", "assistant") and t.content
    ]
    result = run_assistant(body.message, history, db, org_id)
    return ChatResponse(reply=result["reply"], tools_used=result.get("tools_used", []))
