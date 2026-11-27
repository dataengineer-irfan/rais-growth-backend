from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import require_admin
from app.models.entities import B2BLead, LeadDiscoveryResult, LeadStatus
from app.services.automation_engine import automation_engine, compute_lead_score

router = APIRouter(
    prefix="/discovery",
    tags=["B2B Lead Discovery (Google Places API)"],
    dependencies=[Depends(require_admin)],
)


class DiscoverySearchPayload(BaseModel):
    category: str = Field(default="cafe", max_length=80)
    location: str = Field(default="Rayachoty, Andhra Pradesh", max_length=120)
    radius_meters: int = Field(default=15000, ge=1000, le=50000)


def _serialize_discovery(d: LeadDiscoveryResult) -> Dict[str, Any]:
    return {
        "id": d.id,
        "place_id": d.place_id,
        "business_name": d.business_name,
        "address": d.address,
        "phone": d.phone,
        "website": d.website,
        "maps_url": d.maps_url,
        "category": d.category,
        "location_query": d.location_query,
        "rating": d.rating,
        "user_ratings_total": d.user_ratings_total,
        "lead_score": d.lead_score,
        "converted_lead_id": d.converted_lead_id,
        "discovered_at": d.discovered_at.isoformat() if d.discovered_at else None,
        "last_refreshed_at": d.last_refreshed_at.isoformat() if d.last_refreshed_at else None,
    }


@router.get("")
async def list_discoveries(db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(select(LeadDiscoveryResult).order_by(desc(LeadDiscoveryResult.discovered_at)))
    ).scalars().all()
    return {
        "api_configured": bool(settings.GOOGLE_PLACES_API_KEY),
        "results": [_serialize_discovery(r) for r in rows],
    }


@router.post("/search")
async def search_google_places(body: DiscoverySearchPayload, db: AsyncSession = Depends(get_db)):
    """
    Calls official Google Places API (New) text search.
    Never fabricates results when GOOGLE_PLACES_API_KEY is missing or unauthorized.
    """
    api_key = (settings.GOOGLE_PLACES_API_KEY or "").strip()
    if not api_key:
        return {
            "status": "NOT_CONFIGURED",
            "api_configured": False,
            "message": "GOOGLE_PLACES_API_KEY is not configured on the backend. Configure a Places API (New) key to run live discovery.",
            "discovered_count": 0,
            "results": [],
        }

    text_query = f"{body.category} in {body.location}"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": (
            "places.id,places.displayName,places.formattedAddress,"
            "places.nationalPhoneNumber,places.websiteUri,places.googleMapsUri,"
            "places.primaryTypeDisplayName,places.rating,places.userRatingCount"
        ),
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                "https://places.googleapis.com/v1/places:searchText",
                headers=headers,
                json={"textQuery": text_query, "maxResultCount": 20},
            )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to contact Google Places API: {exc}")

    if resp.status_code in (401, 403):
        return {
            "status": "PERMISSION_MISSING",
            "api_configured": True,
            "message": f"Google Places API authorization failed ({resp.status_code}): {resp.text[:250]}",
            "discovered_count": 0,
            "results": [],
        }
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=f"Google Places API error: {resp.text[:300]}")

    places = resp.json().get("places") or []
    saved: List[LeadDiscoveryResult] = []
    for p in places:
        place_id = p.get("id")
        name = (p.get("displayName") or {}).get("text")
        if not place_id or not name:
            continue
        existing = (
            await db.execute(select(LeadDiscoveryResult).where(LeadDiscoveryResult.place_id == place_id))
        ).scalar_one_or_none()
        rating = p.get("rating")
        reviews = p.get("userRatingCount") or 0
        score = min(100, 45 + (15 if p.get("nationalPhoneNumber") else 0) + (15 if (rating or 0) >= 4.0 else 5) + (15 if reviews >= 20 else 5))
        if existing:
            existing.business_name = name
            existing.address = p.get("formattedAddress")
            existing.phone = p.get("nationalPhoneNumber")
            existing.website = p.get("websiteUri")
            existing.maps_url = p.get("googleMapsUri")
            existing.rating = rating
            existing.user_ratings_total = reviews
            existing.lead_score = score
            existing.last_refreshed_at = datetime.now(timezone.utc)
            saved.append(existing)
        else:
            rec = LeadDiscoveryResult(
                place_id=place_id,
                business_name=name,
                address=p.get("formattedAddress"),
                phone=p.get("nationalPhoneNumber"),
                website=p.get("websiteUri"),
                maps_url=p.get("googleMapsUri"),
                category=(p.get("primaryTypeDisplayName") or {}).get("text") or body.category,
                location_query=body.location,
                rating=rating,
                user_ratings_total=reviews,
                lead_score=score,
            )
            db.add(rec)
            saved.append(rec)

    await db.commit()
    for r in saved:
        await db.refresh(r)

    return {
        "status": "SUCCESS",
        "api_configured": True,
        "discovered_count": len(saved),
        "results": [_serialize_discovery(r) for r in saved],
    }


@router.post("/{discovery_id}/convert-to-crm")
async def convert_discovery_to_crm(discovery_id: int, db: AsyncSession = Depends(get_db)):
    rec = (
        await db.execute(select(LeadDiscoveryResult).where(LeadDiscoveryResult.id == discovery_id))
    ).scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=404, detail="Discovered business not found")

    if rec.converted_lead_id:
        existing_lead = (
            await db.execute(select(B2BLead).where(B2BLead.id == rec.converted_lead_id))
        ).scalar_one_or_none()
        if existing_lead:
            return {"status": "ALREADY_IN_CRM", "duplicate": True, "lead_id": existing_lead.id}

    # Deduplicate by phone or normalized name
    norm_digits = "".join(c for c in (rec.phone or "") if c.isdigit())[-10:]
    all_leads = (await db.execute(select(B2BLead))).scalars().all()
    for l in all_leads:
        l_digits = "".join(c for c in (l.phone or "") if c.isdigit())[-10:]
        if (norm_digits and l_digits == norm_digits) or l.business_name.strip().lower() == rec.business_name.strip().lower():
            rec.converted_lead_id = l.id
            await db.commit()
            return {"status": "DUPLICATE_MATCHED", "duplicate": True, "lead_id": l.id}

    lead = B2BLead(
        business_name=rec.business_name,
        phone=rec.phone or "UNAVAILABLE",
        business_type=rec.category or "Restaurant",
        location=rec.location_query or "Rayachoty",
        lead_source="Google Places API",
        notes=f"Maps: {rec.maps_url or 'N/A'} | Address: {rec.address or 'N/A'}",
        status=LeadStatus.NEW,
    )
    score, segment = compute_lead_score(lead)
    lead.lead_score = score
    lead.segment = segment
    db.add(lead)
    await db.commit()
    await db.refresh(lead)

    rec.converted_lead_id = lead.id
    await db.commit()

    await automation_engine.trigger_event(
        db=db,
        trigger_type="new_lead",
        payload={
            "lead_id": lead.id,
            "business_name": lead.business_name,
            "phone": lead.phone,
            "business_type": lead.business_type,
            "location": lead.location,
        },
        idempotency_key=f"discovery-lead-{lead.id}",
    )

    return {"status": "CREATED", "duplicate": False, "lead_id": lead.id}
