from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.core.database import get_db
from app.models.entities import Review, ReviewReplyDraft
from app.schemas.schemas import ReviewRead, ReviewReplyApproval
from app.services.review_service import review_service

router = APIRouter(prefix="/reviews", tags=["Reviews & Reputation Management"])

@router.get("", response_model=List[ReviewRead])
async def list_reviews(db: AsyncSession = Depends(get_db)):
    """List all reviews with their generated response drafts."""
    stmt = select(Review).options(selectinload(Review.reply_drafts)).order_by(Review.create_time.desc())
    res = await db.execute(stmt)
    return res.scalars().all()

@router.post("/seed-authentic")
async def seed_authentic_reviews_endpoint(db: AsyncSession = Depends(get_db)):
    """Seed the 4 authentic Google Maps customer reviews with bilingual Telugu/English response drafts."""
    from app.seed_data.seed import seed_initial_data
    await seed_initial_data(db)
    stmt = select(Review).options(selectinload(Review.reply_drafts)).order_by(Review.create_time.desc())
    res = await db.execute(stmt)
    reviews = res.scalars().all()
    return {"status": "SUCCESS", "seeded_reviews_count": len(reviews)}

@router.post("/sync")
async def sync_reviews(db: AsyncSession = Depends(get_db)):
    """Sync latest reviews from Google Business Profile and generate response drafts."""
    count = await review_service.sync_reviews_from_gbp(db)
    return {"status": "SUCCESS", "new_reviews_synced": count}

@router.post("/test-review")
async def create_test_review(
    rating: int = 5,
    author_name: str = "Rayachoty Cafe Partner",
    comment: str = "Best wholesale frozen snacks and Amul fries supply in Rayachoty! Delivered at -18C on time.",
    db: AsyncSession = Depends(get_db)
):
    """Generates an authentic customer review with pending bilingual AI drafts to demonstrate approval gate."""
    rev = await review_service.create_test_review(db=db, author_name=author_name, rating=rating, comment=comment)
    return {"status": "SUCCESS", "review_id": rev.id}

@router.post("/reply/{draft_id}/approve")
async def approve_and_publish_reply(draft_id: int, approval_data: ReviewReplyApproval, db: AsyncSession = Depends(get_db)):
    """
    MANDATORY 1-CLICK HUMAN APPROVAL WORKFLOW:
    Explicitly approves and publishes a response to Google Business Profile.
    """
    try:
        return await review_service.approve_and_publish_reply(
            db=db,
            draft_id=draft_id,
            custom_reply_text=approval_data.reply_text,
            approver_name=approval_data.approver_name
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
