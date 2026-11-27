from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.security import require_admin
from app.models.entities import B2BLead
from app.schemas.schemas import B2BLeadRead, B2BLeadCreate, B2BLeadUpdate
from app.core.audit import log_audit

router = APIRouter(prefix="/leads", tags=["B2B Lead Management"])

@router.get("", response_model=List[B2BLeadRead], dependencies=[Depends(require_admin)])
async def list_leads(db: AsyncSession = Depends(get_db)):
    """List all commercial leads."""
    stmt = select(B2BLead).order_by(B2BLead.created_at.desc())
    res = await db.execute(stmt)
    return res.scalars().all()

@router.post("", response_model=B2BLeadRead)
async def create_lead(data: B2BLeadCreate, db: AsyncSession = Depends(get_db)):
    """Add a new commercial kitchen inquiry (callable from public storefront quote builder or admin CRM)."""
    from app.services.automation_engine import automation_engine, compute_lead_score

    new_lead = B2BLead(**data.model_dump())
    score, segment = compute_lead_score(new_lead)
    new_lead.lead_score = score
    new_lead.segment = segment
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
    await automation_engine.trigger_event(
        db=db,
        trigger_type="new_lead",
        payload={
            "lead_id": new_lead.id,
            "business_name": new_lead.business_name,
            "phone": new_lead.phone,
            "business_type": new_lead.business_type,
            "location": new_lead.location,
            "product_interest": new_lead.product_interest,
        },
        idempotency_key=f"lead-{new_lead.id}",
    )
    await db.refresh(new_lead)
    return new_lead

@router.put("/{lead_id}", response_model=B2BLeadRead, dependencies=[Depends(require_admin)])
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

@router.post("/{lead_id}/trigger-review-request", dependencies=[Depends(require_admin)])
async def trigger_lead_review_request(lead_id: int, db: AsyncSession = Depends(get_db)):
    """
    Automated Post-Order Review Velocity Engine (Google Prominence):
    Generates a personalized WhatsApp dispatch link containing the direct 1-click
    Google Maps review URL to accelerate verified customer reviews from commercial buyers.
    """
    from app.services.nap_citation_service import nap_citation_service

    stmt = select(B2BLead).where(B2BLead.id == lead_id)
    res = await db.execute(stmt)
    lead = res.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    cust_name = lead.contact_person or lead.business_name or "Valued Partner"
    phone = lead.phone or "9347453135"

    dispatch_data = nap_citation_service.generate_review_request(
        customer_name=cust_name,
        phone=phone,
        order_summary=f"supplying {lead.business_name} in {lead.address or 'Rayachoty'}"
    )

    await log_audit(
        db=db,
        action="REVIEW_REQUEST_DISPATCHED",
        resource_type="LEAD",
        resource_id=str(lead.id),
        details={"customer": cust_name, "phone": phone}
    )

    return {
        "status": "SUCCESS",
        "lead_id": lead.id,
        "business_name": lead.business_name,
        **dispatch_data
    }
