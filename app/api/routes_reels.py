import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_admin
from app.models.entities import (
    ReelAssetStatus,
    ReelsAsset,
    YouTubeQueueItem,
    YouTubeQueueStatus,
)
from app.services.meta_service import MetaService
from app.api.routes_youtube import download_drive_video_bytes
from app.core.config import settings

router = APIRouter(
    prefix="/reels",
    tags=["Reels Video Studio"],
    dependencies=[Depends(require_admin)],
)


class ReelCreatePayload(BaseModel):
    title: str = Field(..., min_length=2, max_length=250)
    brand: str = "RAIS Agencies"
    product_sku: Optional[str] = None
    product_name: Optional[str] = None
    theme: str = "frozen_products"
    drive_file_id: Optional[str] = None
    video_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    duration_seconds: Optional[int] = None
    resolution: str = "1080x1920"
    aspect_ratio: str = "9:16"
    platforms: List[str] = Field(default_factory=lambda: ["instagram", "facebook", "youtube"])
    caption_english: Optional[str] = None
    caption_telugu: Optional[str] = None
    caption_hindi: Optional[str] = None
    hashtags: Optional[str] = None
    campaign_id: Optional[int] = None
    scheduled_for: Optional[datetime] = None


class ReelUpdatePayload(BaseModel):
    title: Optional[str] = None
    product_sku: Optional[str] = None
    product_name: Optional[str] = None
    theme: Optional[str] = None
    video_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    duration_seconds: Optional[int] = None
    resolution: Optional[str] = None
    aspect_ratio: Optional[str] = None
    platforms: Optional[List[str]] = None
    caption_english: Optional[str] = None
    caption_telugu: Optional[str] = None
    caption_hindi: Optional[str] = None
    hashtags: Optional[str] = None
    campaign_id: Optional[int] = None
    scheduled_for: Optional[datetime] = None
    status: Optional[ReelAssetStatus] = None


def _serialize_reel(r: ReelsAsset) -> Dict[str, Any]:
    return {
        "id": r.id,
        "drive_file_id": r.drive_file_id,
        "youtube_queue_item_id": r.youtube_queue_item_id,
        "title": r.title,
        "brand": r.brand,
        "product_sku": r.product_sku,
        "product_name": r.product_name,
        "theme": r.theme,
        "video_url": r.video_url,
        "thumbnail_url": r.thumbnail_url,
        "duration_seconds": r.duration_seconds,
        "resolution": r.resolution,
        "aspect_ratio": r.aspect_ratio,
        "platforms": json.loads(r.platforms_json or '["instagram","facebook","youtube"]'),
        "caption_english": r.caption_english,
        "caption_telugu": r.caption_telugu,
        "caption_hindi": r.caption_hindi,
        "hashtags": r.hashtags,
        "campaign_id": r.campaign_id,
        "scheduled_for": r.scheduled_for.isoformat() if r.scheduled_for else None,
        "status": r.status.value if hasattr(r.status, "value") else str(r.status),
        "published_url": r.published_url,
        "platform_post_id": r.platform_post_id,
        "error_history": json.loads(r.error_history_json or "[]"),
        "approved_by": r.approved_by,
        "approved_at": r.approved_at.isoformat() if r.approved_at else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


@router.get("")
async def list_reels(
    status: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(ReelsAsset).order_by(desc(ReelsAsset.created_at))
    if status and status.upper() != "ALL":
        try:
            st_enum = ReelAssetStatus(status.upper())
            stmt = stmt.where(ReelsAsset.status == st_enum)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid reel status: {status}")
    rows = (await db.execute(stmt)).scalars().all()
    return [_serialize_reel(r) for r in rows]


@router.post("/sync-from-drive-queue")
async def sync_reels_from_drive_queue(db: AsyncSession = Depends(get_db)):
    """Imports real Google Drive / YouTube queue items into persistent ReelsAsset records."""
    q_items = (await db.execute(select(YouTubeQueueItem).order_by(YouTubeQueueItem.id))).scalars().all()
    existing_drive_ids = {
        r.drive_file_id: r
        for r in (await db.execute(select(ReelsAsset).where(ReelsAsset.drive_file_id.isnot(None)))).scalars().all()
    }
    imported = 0
    updated = 0
    for q in q_items:
        is_ig_pub = q.ig_status == "PUBLISHED" and bool(q.ig_url)
        is_yt_pub = q.status == YouTubeQueueStatus.PUBLISHED and bool(q.youtube_url)
        is_fb_pub = q.fb_status == "PUBLISHED" and bool(q.fb_url)
        pub_url = q.ig_url or q.fb_url or q.youtube_url
        pub_id = q.ig_media_id or q.fb_video_id or q.youtube_video_id

        if is_ig_pub or is_yt_pub or is_fb_pub:
            derived_status = ReelAssetStatus.PUBLISHED
        elif q.status == YouTubeQueueStatus.FAILED or q.ig_status == "FAILED":
            derived_status = ReelAssetStatus.FAILED
        elif q.scheduled_for:
            derived_status = ReelAssetStatus.SCHEDULED
        else:
            derived_status = ReelAssetStatus.AWAITING_APPROVAL

        if q.drive_file_id in existing_drive_ids:
            rec = existing_drive_ids[q.drive_file_id]
            rec.youtube_queue_item_id = q.id
            if pub_url:
                rec.published_url = pub_url
                rec.platform_post_id = pub_id
                rec.status = ReelAssetStatus.PUBLISHED
            updated += 1
        else:
            rec = ReelsAsset(
                drive_file_id=q.drive_file_id,
                youtube_queue_item_id=q.id,
                title=q.video_title,
                product_sku=q.product_sku,
                product_name=q.product_name,
                caption_english=q.description,
                hashtags=q.tags,
                scheduled_for=q.scheduled_for,
                status=derived_status,
                published_url=pub_url,
                platform_post_id=pub_id,
            )
            db.add(rec)
            imported += 1
    await db.commit()
    return {"status": "SYNCED", "imported": imported, "updated": updated}


@router.post("")
async def create_reel(body: ReelCreatePayload, db: AsyncSession = Depends(get_db)):
    if not body.drive_file_id and not body.video_url:
        raise HTTPException(
            status_code=400,
            detail="A real drive_file_id or video_url is required. Metadata-only fake MP4 records are not allowed.",
        )
    rec = ReelsAsset(
        title=body.title.strip(),
        brand=body.brand,
        product_sku=body.product_sku,
        product_name=body.product_name,
        theme=body.theme,
        drive_file_id=body.drive_file_id,
        video_url=body.video_url,
        thumbnail_url=body.thumbnail_url,
        duration_seconds=body.duration_seconds,
        resolution=body.resolution,
        aspect_ratio=body.aspect_ratio,
        platforms_json=json.dumps(body.platforms),
        caption_english=body.caption_english,
        caption_telugu=body.caption_telugu,
        caption_hindi=body.caption_hindi,
        hashtags=body.hashtags,
        campaign_id=body.campaign_id,
        scheduled_for=body.scheduled_for,
        status=ReelAssetStatus.AWAITING_APPROVAL,
    )
    db.add(rec)
    await db.commit()
    await db.refresh(rec)
    return _serialize_reel(rec)


@router.put("/{reel_id}")
async def update_reel(reel_id: int, body: ReelUpdatePayload, db: AsyncSession = Depends(get_db)):
    rec = (await db.execute(select(ReelsAsset).where(ReelsAsset.id == reel_id))).scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=404, detail="Reel asset not found")
    data = body.model_dump(exclude_unset=True)
    if "platforms" in data:
        rec.platforms_json = json.dumps(data.pop("platforms"))
    if data.get("status") == ReelAssetStatus.PUBLISHED and not rec.published_url:
        raise HTTPException(
            status_code=400,
            detail="Cannot mark reel as PUBLISHED without confirmed platform publication URL.",
        )
    for k, v in data.items():
        setattr(rec, k, v)
    await db.commit()
    await db.refresh(rec)
    return _serialize_reel(rec)


@router.post("/{reel_id}/approve")
async def approve_reel(
    reel_id: int,
    admin_user: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    rec = (await db.execute(select(ReelsAsset).where(ReelsAsset.id == reel_id))).scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=404, detail="Reel asset not found")
    rec.approved_by = admin_user
    rec.approved_at = datetime.now(timezone.utc)
    rec.status = ReelAssetStatus.SCHEDULED if rec.scheduled_for else ReelAssetStatus.AWAITING_APPROVAL
    await db.commit()
    await db.refresh(rec)
    return _serialize_reel(rec)


@router.post("/{reel_id}/publish")
async def publish_reel(reel_id: int, db: AsyncSession = Depends(get_db)):
    """Publishes a reel through the real Meta Graph API / YouTube Queue pipeline. Never fabricates success."""
    rec = (await db.execute(select(ReelsAsset).where(ReelsAsset.id == reel_id))).scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=404, detail="Reel asset not found")
    if not rec.youtube_queue_item_id and not rec.drive_file_id:
        raise HTTPException(
            status_code=400,
            detail="Reel must be linked to a Google Drive video or YouTubeQueueItem for automated publishing.",
        )
    q_item = None
    if rec.youtube_queue_item_id:
        q_item = (
            await db.execute(select(YouTubeQueueItem).where(YouTubeQueueItem.id == rec.youtube_queue_item_id))
        ).scalar_one_or_none()
    if not q_item and rec.drive_file_id:
        q_item = (
            await db.execute(select(YouTubeQueueItem).where(YouTubeQueueItem.drive_file_id == rec.drive_file_id))
        ).scalar_one_or_none()
    if not q_item:
        raise HTTPException(
            status_code=400,
            detail="No linked Drive queue item found. Sync the Drive folder in Drive -> YT, IG & FB first.",
        )

    rec.status = ReelAssetStatus.PUBLISHING
    await db.commit()

    platforms = [p for p in json.loads(rec.platforms_json or '["instagram","facebook"]') if p in ("instagram", "facebook")]
    if not platforms:
        platforms = ["instagram", "facebook"]

    try:
        outcome = await MetaService.publish_queue_item(
            db=db,
            item=q_item,
            platforms=platforms,
            download_bytes_fn=download_drive_video_bytes,
            base_url=settings.BACKEND_PUBLIC_URL or None,
        )
        pub_url = q_item.ig_url or q_item.fb_url or q_item.youtube_url
        pub_id = q_item.ig_media_id or q_item.fb_video_id or q_item.youtube_video_id
        if pub_url:
            rec.status = ReelAssetStatus.PUBLISHED
            rec.published_url = pub_url
            rec.platform_post_id = pub_id
        else:
            rec.status = ReelAssetStatus.FAILED
            errs = json.loads(rec.error_history_json or "[]")
            errs.append({"at": datetime.now(timezone.utc).isoformat(), "error": str(outcome)})
            rec.error_history_json = json.dumps(errs[-10:])
        await db.commit()
        await db.refresh(rec)
        return {"outcome": outcome, "reel": _serialize_reel(rec)}
    except Exception as exc:
        rec.status = ReelAssetStatus.FAILED
        errs = json.loads(rec.error_history_json or "[]")
        errs.append({"at": datetime.now(timezone.utc).isoformat(), "error": str(exc)})
        rec.error_history_json = json.dumps(errs[-10:])
        await db.commit()
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/{reel_id}")
async def delete_reel(reel_id: int, db: AsyncSession = Depends(get_db)):
    rec = (await db.execute(select(ReelsAsset).where(ReelsAsset.id == reel_id))).scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=404, detail="Reel asset not found")
    await db.delete(rec)
    await db.commit()
    return {"status": "DELETED", "id": reel_id}
