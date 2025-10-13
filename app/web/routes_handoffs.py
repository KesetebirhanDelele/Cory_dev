# app/web/routes_handoffs.py
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from uuid import UUID
from app.repo.handoff_repo import HandoffRepo

# If you already expose a DB pool dependency, import it instead:
# from app.data.db_pg import get_pool  # <- preferred if available

router = APIRouter(prefix="/api/v1/handoffs", tags=["handoffs"])

# --- Minimal deps (adapt if you already have these in middleware/db modules) ---

async def get_pool(request: Request):
    """
    Matches common pattern in your app: store the asyncpg pool on app.state.db_pool.
    If your project exposes a helper in app/data/db_pg.py, replace this with that import.
    """
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise RuntimeError("DB pool not initialized on app.state.db_pool")
    return pool

class Identity(BaseModel):
    organization_id: UUID
    user_id: UUID

async def get_identity(request: Request) -> Identity:
    """
    Pull org/user from middleware-injected request.state.auth OR headers.
    Adjust if your middleware sets different attribute names.
    """
    ctx = getattr(request.state, "auth", None) or {}
    org = ctx.get("organization_id") or request.headers.get("X-Org-Id")
    uid = ctx.get("user_id") or request.headers.get("X-User-Id")
    if not org or not uid:
        raise HTTPException(status_code=401, detail="Missing auth context")
    try:
        return Identity(organization_id=UUID(str(org)), user_id=UUID(str(uid)))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid auth identifiers")

# --- Schemas (kept local so you don't have to edit app/web/schemas.py) ---

class HandoffCreateRequest(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    task_type: str = Field(..., min_length=2, max_length=64)
    source: str = "system"
    source_key: Optional[str] = None
    lead_id: Optional[UUID] = None
    interaction_id: Optional[UUID] = None
    description: Optional[str] = None
    priority: str = Field("normal", pattern=r"^(low|normal|high|urgent)$")
    assigned_to: Optional[UUID] = None
    metadata: Dict[str, Any] = {}

class ResolveRequest(BaseModel):
    resolution_note: Optional[str] = None
    outcome_snapshot: Dict[str, Any] = Field(default_factory=dict)

class HandoffResponse(BaseModel):
    id: UUID
    organization_id: UUID
    lead_id: Optional[UUID]
    interaction_id: Optional[UUID]
    task_type: str
    source: str
    source_key: Optional[str]
    title: str
    description: Optional[str]
    priority: str
    status: str
    assigned_to: Optional[UUID]
    sla_due_at: Optional[str]
    first_response_at: Optional[str]
    resolved_at: Optional[str]
    outcome_snapshot: Dict[str, Any]
    metadata: Dict[str, Any]

# --- Routes -------------------------------------------------------------------

@router.post("", response_model=HandoffResponse)
async def create_handoff(
    body: HandoffCreateRequest,
    ident: Identity = Depends(get_identity),
    pool = Depends(get_pool),
):
    repo = HandoffRepo(pool)
    rec = await repo.create(
        organization_id=ident.organization_id,
        title=body.title,
        task_type=body.task_type,
        source=body.source,
        source_key=body.source_key,
        lead_id=body.lead_id,
        interaction_id=body.interaction_id,
        description=body.description,
        priority=body.priority,
        assigned_to=body.assigned_to,
        metadata=body.metadata,
    )
    if rec["organization_id"] != ident.organization_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    return rec

@router.post("/{handoff_id}/resolve", response_model=HandoffResponse)
async def resolve_handoff(
    handoff_id: UUID,
    body: ResolveRequest,
    ident: Identity = Depends(get_identity),
    pool = Depends(get_pool),
):
    repo = HandoffRepo(pool)
    # Optional: record first response when resolver acts
    await repo.mark_first_response(handoff_id=handoff_id)
    rec = await repo.resolve(
        handoff_id=handoff_id,
        resolved_by=ident.user_id,
        resolution_note=body.resolution_note,
        outcome_snapshot=body.outcome_snapshot,
    )
    if rec["organization_id"] != ident.organization_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    return rec

@router.get("/{handoff_id}", response_model=HandoffResponse)
async def get_handoff(
    handoff_id: UUID,
    ident: Identity = Depends(get_identity),
    pool = Depends(get_pool),
):
    repo = HandoffRepo(pool)
    rec = await repo.get(handoff_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Not found")
    if rec["organization_id"] != ident.organization_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    return rec
