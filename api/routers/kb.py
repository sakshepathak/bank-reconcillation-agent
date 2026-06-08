"""Knowledge-base maintenance endpoints (org-scoped)."""
from fastapi import APIRouter, Depends
from sqlmodel import Session

from api.deps import get_db, get_current_org_id

router = APIRouter(prefix="/kb", tags=["kb"])


@router.post("/sync")
def sync_kb(
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
) -> dict:
    """Refresh this organisation's company + contact info in the knowledge base
    so the assistant can answer questions about the business. Idempotent —
    safe to call repeatedly; it overwrites in place."""
    # Lazy import: pulls in the embedding stack only when actually called, so it
    # never slows app startup or unrelated requests/tests.
    from knowledge_base.org_sync import sync_org_to_kb
    return sync_org_to_kb(db, org_id)
