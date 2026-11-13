from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.core.database import get_db
from app.models.entities import Campaign, CampaignPost, PostStatus, VerificationStatus
from app.schemas.schemas import CampaignRead, CampaignCreate, CampaignPostRead, CampaignPostCreate, PublishCycleResponse
from app.services.ai_content_engine import ai_content_engine
from app.services.scheduler_service import scheduler_service

router = APIRouter(prefix="/campaigns", tags=["Campaigns & Content Studio"])

@router.get("", response_model=List[CampaignRead])
async def list_campaigns(db: AsyncSession = Depends(get_db)):
    """List all marketing campaigns with their posts."""
    stmt = select(Campaign).options(selectinload(Campaign.posts)).order_by(Campaign.id.desc())
    res = await db.execute(stmt)
    return res.scalars().all()

@router.post("", response_model=CampaignRead)
async def create_campaign(data: CampaignCreate, db: AsyncSession = Depends(get_db)):
    """Create a new campaign with draft posts."""
    new_campaign = Campaign(
        title=data.title,
        objective=data.objective,
        theme=data.theme,
        status=PostStatus.DRAFT,
        is_approved_by_user=False
    )
    db.add(new_campaign)
    await db.flush()

    for p in data.posts:
        post_obj = CampaignPost(
            campaign_id=new_campaign.id,
            headline=p.headline,
            content_english=p.content_english,
            content_telugu=p.content_telugu,
            call_to_action=p.call_to_action,
            target_product_sku=p.target_product_sku,
            media_url=p.media_url,
            status=PostStatus.DRAFT,
            verification_status=VerificationStatus.UNVERIFIED_DRAFT
        )
        db.add(post_obj)

    await db.commit()
    await db.refresh(new_campaign)
    return new_campaign

@router.post("/{campaign_id}/approve")
async def approve_and_schedule_campaign(campaign_id: int, db: AsyncSession = Depends(get_db)):
    """
    Explicit user approval of a campaign.
    Converts drafts into scheduled posts and registers them in the publishing queue.
    """
    try:
        return await scheduler_service.approve_and_schedule_campaign(db, campaign_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/generate-post")
async def generate_post(
    theme: str = "B2B Snacks Promotion",
    target_sku: Optional[str] = None,
    language_mode: str = "bilingual",
    db: AsyncSession = Depends(get_db)
):
    """Generates an AI post and runs deterministic validation checks."""
    return await ai_content_engine.generate_campaign_post(
        db=db,
        theme=theme,
        target_sku=target_sku,
        language_mode=language_mode
    )

@router.post("/trigger-publish-cycle", response_model=PublishCycleResponse)
async def trigger_publish_cycle(db: AsyncSession = Depends(get_db)):
    """Manually triggers a check on the publishing queue to publish ready posts."""
    return await scheduler_service.execute_publishing_cycle(db)
