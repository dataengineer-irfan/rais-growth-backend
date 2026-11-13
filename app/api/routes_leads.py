from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.models.entities import B2BLead
from app.schemas.schemas import B2BLeadRead, B2BLeadCreate, B2BLeadUpdate
from app.core.audit import log_audit

router = APIRouter(prefix="/leads", tags=["B2B Lead Management"])

@router.get("", response_model=List[B2BLeadRead])
async def list_leads(db: AsyncSession = Depends(get_db)):
    """List all commercial leads."""
    stmt = select(B2BLead).order_by(B2BLead.created_at.desc())
    res = await db.execute(stmt)
    return res.scalars().all()

@router.post("", response_model=B2BLeadRead)
async def create_lead(data: B2BLeadCreate, db: AsyncSession = Depends(get_db)):
    """Add a new commercial kitchen inquiry."""
    new_lead = B2BLead(**data.model_dump())
    db.add(new_lead)
    await db.commit()
    await db.refresh(new_lead)

    await log_audit(
        db=db,
        action="B2B_LEAD_RECORDED",
        resource_type="LEAD",
        resource_id=str(new_lead.id),
        details={"business": new_lead.business_name, "phone": new_lead.phone}
    )
    return new_lead

@router.put("/{lead_id}", response_model=B2BLeadRead)
async def update_lead(lead_id: int, data: B2BLeadUpdate, db: AsyncSession = Depends(get_db)):
    """Update lead status or follow-up notes."""
    stmt = select(B2BLead).where(B2BLead.id == lead_id)
    res = await db.execute(stmt)
    lead = res.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(lead, k, v)
    await db.commit()
    await db.refresh(lead)
    return lead
