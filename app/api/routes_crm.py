import csv
import io
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_admin
from app.models.entities import (
    B2BLead,
    CatalogSKU,
    CustomerEnquiry,
    CustomerInteraction,
    LeadStatus,
)
from app.services.automation_engine import automation_engine, compute_lead_score

router = APIRouter(
    prefix="/crm",
    tags=["AI-Powered B2B CRM & Enquiries"],
    dependencies=[Depends(require_admin)],
)


class InteractionCreatePayload(BaseModel):
    channel: str = "CRM"
    direction: str = "OUTBOUND"
    summary: str = Field(..., min_length=2)


class EnquiryCreatePayload(BaseModel):
    lead_id: Optional[int] = None
    channel: str = "MANUAL"
    customer_name: str = Field(..., min_length=2)
    phone: str = Field(..., min_length=6)
    product_sku: Optional[str] = None
    quantity_text: Optional[str] = None
    notes: Optional[str] = None
    linked_order_ref: Optional[str] = None


class BulkLeadItem(BaseModel):
    business_name: str
    contact_person: Optional[str] = None
    phone: str
    business_type: str = "Cafe"
    location: str = "Rayachoty"
    product_interest: Optional[str] = None


@router.get("/leads")
async def list_crm_leads(
    segment: Optional[str] = None,
    status: Optional[str] = None,
    q: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(select(B2BLead).order_by(desc(B2BLead.created_at)))).scalars().all()
    results = []
    for l in rows:
        if segment and segment != "ALL" and (l.segment or "") != segment:
            continue
        if status and status != "ALL" and l.status.value != status:
            continue
        if q and q.strip().lower() not in f"{l.business_name} {l.phone} {l.location} {l.product_interest or ''}".lower():
            continue
        results.append(
            {
                "id": l.id,
                "business_name": l.business_name,
                "contact_person": l.contact_person,
                "phone": l.phone,
                "business_type": l.business_type,
                "location": l.location,
                "product_interest": l.product_interest,
                "status": l.status.value if hasattr(l.status, "value") else str(l.status),
                "lead_source": l.lead_source,
                "notes": l.notes,
                "assigned_owner": l.assigned_owner,
                "lead_score": l.lead_score,
                "segment": l.segment,
                "last_interaction_at": l.last_interaction_at.isoformat() if l.last_interaction_at else None,
                "next_followup_at": l.next_followup_at.isoformat() if l.next_followup_at else None,
                "opted_out_whatsapp": bool(l.opted_out_whatsapp),
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
        )
    return results


@router.post("/leads/bulk-import")
async def bulk_import_leads(items: List[BulkLeadItem], db: AsyncSession = Depends(get_db)):
    existing = (await db.execute(select(B2BLead))).scalars().all()
    existing_phones = {"".join(c for c in (l.phone or "") if c.isdigit())[-10:] for l in existing}
    existing_names = {l.business_name.strip().lower() for l in existing}

    created = 0
    skipped_duplicates = 0
    for item in items:
        digits = "".join(c for c in item.phone if c.isdigit())[-10:]
        if (digits and digits in existing_phones) or item.business_name.strip().lower() in existing_names:
            skipped_duplicates += 1
            continue
        lead = B2BLead(
            business_name=item.business_name.strip(),
            contact_person=item.contact_person,
            phone=item.phone.strip(),
            business_type=item.business_type,
            location=item.location,
            product_interest=item.product_interest,
            lead_source="Bulk Import",
        )
        score, seg = compute_lead_score(lead)
        lead.lead_score = score
        lead.segment = seg
        db.add(lead)
        if digits:
            existing_phones.add(digits)
        existing_names.add(lead.business_name.lower())
        created += 1
    await db.commit()
    return {"created": created, "skipped_duplicates": skipped_duplicates}


@router.get("/leads/export.csv")
async def export_leads_csv(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(B2BLead).order_by(desc(B2BLead.created_at)))).scalars().all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "business_name", "contact_person", "phone", "business_type", "location", "status", "lead_score", "segment", "lead_source", "created_at"])
    for l in rows:
        writer.writerow([
            l.id, l.business_name, l.contact_person or "", l.phone, l.business_type,
            l.location, l.status.value, l.lead_score, l.segment, l.lead_source,
            l.created_at.isoformat() if l.created_at else "",
        ])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="rais_b2b_leads.csv"'},
    )


@router.get("/leads/{lead_id}/interactions")
async def list_interactions(lead_id: int, db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(CustomerInteraction)
            .where(CustomerInteraction.lead_id == lead_id)
            .order_by(desc(CustomerInteraction.created_at))
        )
    ).scalars().all()
    return [
        {
            "id": i.id,
            "lead_id": i.lead_id,
            "channel": i.channel,
            "direction": i.direction,
            "summary": i.summary,
            "created_by": i.created_by,
            "created_at": i.created_at.isoformat() if i.created_at else None,
        }
        for i in rows
    ]


@router.post("/leads/{lead_id}/interactions")
async def add_interaction(
    lead_id: int,
    body: InteractionCreatePayload,
    admin_user: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    lead = (await db.execute(select(B2BLead).where(B2BLead.id == lead_id))).scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    rec = CustomerInteraction(
        lead_id=lead_id,
        channel=body.channel,
        direction=body.direction,
        summary=body.summary,
        created_by=admin_user,
    )
    lead.last_interaction_at = datetime.now(timezone.utc)
    db.add(rec)
    await db.commit()
    await db.refresh(rec)
    return {"id": rec.id, "summary": rec.summary, "created_at": rec.created_at.isoformat()}


@router.get("/enquiries")
async def list_enquiries(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(CustomerEnquiry).order_by(desc(CustomerEnquiry.created_at)))).scalars().all()
    return [
        {
            "id": e.id,
            "lead_id": e.lead_id,
            "channel": e.channel,
            "customer_name": e.customer_name,
            "phone": e.phone,
            "product_sku": e.product_sku,
            "product_name": e.product_name,
            "quantity_text": e.quantity_text,
            "notes": e.notes,
            "status": e.status,
            "assigned_owner": e.assigned_owner,
            "prepared_response": e.prepared_response,
            "quotation": json.loads(e.quotation_json) if e.quotation_json else None,
            "requires_confirmation": e.requires_confirmation,
            "confirmed_by": e.confirmed_by,
            "linked_order_ref": e.linked_order_ref,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in rows
    ]


@router.post("/enquiries")
async def create_enquiry(body: EnquiryCreatePayload, db: AsyncSession = Depends(get_db)):
    # Match or create CRM lead
    digits = "".join(c for c in body.phone if c.isdigit())[-10:]
    lead = None
    if body.lead_id:
        lead = (await db.execute(select(B2BLead).where(B2BLead.id == body.lead_id))).scalar_one_or_none()
    if not lead and digits:
        lead = (await db.execute(select(B2BLead).where(B2BLead.phone.contains(digits)))).scalar_one_or_none()

    sku_obj = None
    if body.product_sku:
        sku_obj = (await db.execute(select(CatalogSKU).where(CatalogSKU.sku == body.product_sku))).scalar_one_or_none()

    enq = CustomerEnquiry(
        lead_id=lead.id if lead else None,
        channel=body.channel.upper(),
        customer_name=body.customer_name,
        phone=body.phone,
        product_sku=sku_obj.sku if sku_obj else body.product_sku,
        product_name=sku_obj.name if sku_obj else None,
        quantity_text=body.quantity_text,
        notes=body.notes,
        linked_order_ref=body.linked_order_ref,
        status="NEW",
    )
    db.add(enq)
    await db.commit()
    await db.refresh(enq)

    await automation_engine.trigger_event(
        db=db,
        trigger_type="new_enquiry",
        payload={
            "enquiry_id": enq.id,
            "lead_id": lead.id if lead else None,
            "customer_name": enq.customer_name,
            "phone": enq.phone,
            "product_name": enq.product_name or body.product_sku or "RAIS Catalog",
        },
        idempotency_key=f"enquiry-{enq.id}",
    )
    await db.refresh(enq)
    return {"id": enq.id, "status": enq.status, "prepared_response": enq.prepared_response}


@router.post("/enquiries/{enquiry_id}/quotation")
async def build_verified_quotation(
    enquiry_id: int,
    admin_user: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Builds a quotation strictly from verified CatalogSKU data. Never invents prices."""
    enq = (await db.execute(select(CustomerEnquiry).where(CustomerEnquiry.id == enquiry_id))).scalar_one_or_none()
    if not enq:
        raise HTTPException(status_code=404, detail="Enquiry not found")

    sku_obj = None
    if enq.product_sku:
        sku_obj = (await db.execute(select(CatalogSKU).where(CatalogSKU.sku == enq.product_sku))).scalar_one_or_none()

    quotation = {
        "enquiry_id": enq.id,
        "customer_name": enq.customer_name,
        "phone": enq.phone,
        "sku": sku_obj.sku if sku_obj else enq.product_sku,
        "product_name": sku_obj.name if sku_obj else (enq.product_name or "Custom Requirement"),
        "pack_size": sku_obj.pack_size if sku_obj else "Confirmed upon depot call",
        "in_stock": bool(sku_obj.in_stock) if sku_obj else None,
        "verified_selling_price": sku_obj.selling_price if (sku_obj and sku_obj.selling_price is not None) else None,
        "price_note": (
            f"₹{sku_obj.selling_price} / {sku_obj.price_unit or sku_obj.pack_size}"
            if (sku_obj and sku_obj.selling_price is not None)
            else "Verified trade price not stored in SKU record — confirm manually via 9347453135 before sending."
        ),
        "requires_confirmation": True,
        "prepared_by": admin_user,
        "prepared_at": datetime.now(timezone.utc).isoformat(),
    }
    enq.quotation_json = json.dumps(quotation)
    enq.status = "QUOTED"
    await db.commit()
    return quotation


@router.post("/enquiries/{enquiry_id}/confirm")
async def confirm_and_record_enquiry_interaction(
    enquiry_id: int,
    admin_user: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Records human confirmation for a prepared quotation/response and logs CRM interaction."""
    enq = (await db.execute(select(CustomerEnquiry).where(CustomerEnquiry.id == enquiry_id))).scalar_one_or_none()
    if not enq:
        raise HTTPException(status_code=404, detail="Enquiry not found")
    enq.confirmed_by = admin_user
    enq.requires_confirmation = False
    if enq.status in ("NEW", "QUOTED"):
        enq.status = "CONFIRMED"
    if enq.lead_id:
        db.add(
            CustomerInteraction(
                lead_id=enq.lead_id,
                channel=enq.channel,
                direction="OUTBOUND",
                summary=f"Confirmed enquiry #{enq.id} response/quotation for {enq.product_name or enq.product_sku or 'catalog'}",
                created_by=admin_user,
            )
        )
    await db.commit()
    return {"id": enq.id, "status": enq.status, "confirmed_by": enq.confirmed_by}
