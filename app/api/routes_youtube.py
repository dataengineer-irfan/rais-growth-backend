import asyncio
import datetime
import json
import re
from typing import Any, Dict, List, Optional, Tuple
from weakref import WeakKeyDictionary
import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from app.core.config import settings
from app.core.database import AsyncSessionLocal, get_db
from app.core.security import encrypt_token, require_admin, verify_cron_or_admin
from app.models.entities import YouTubeQueueItem, YouTubeDriveSetting, YouTubeQueueStatus, GoogleConnection
from app.schemas.schemas import (
    YouTubeQueueItemRead,
    YouTubeQueueItemUpdate,
    YouTubeDriveSettingRead,
    YouTubeDriveSettingUpdate,
    YouTubeSyncResult,
    YouTubePublishResult,
    MetaPublishRequest,
)
from app.services.gbp_service import gbp_service
from app.services.meta_service import MetaService
from app.services.scheduler_service import SchedulerService
from app.services.video_ai_service import VideoAIService, build_default_first_comment

router = APIRouter(prefix="/youtube", tags=["YouTube & Google Drive Automation"])

DEPOT_PHONE = "9347453135"
DEPOT_ADDRESS = "Beside Indel Money Bank, Sundupalli Road, Near Reddies Colony, Rayachoty – 516269, Annamayya District, Andhra Pradesh"
CORRIDORS = "Rayachoty, Sundupalli, Galiveedu, Kadiri, Chinnamandem, Kalakada, Mahal, Madanapalle, Kadapa, and Rajampet"

DEFAULT_DRIVE_FOLDER_ID = "1Bm_WjSGQb_KQSRz6i08DSsp2mtzOborn"
DEFAULT_DRIVE_FOLDER_NAME = "RAIS_Daily_Promotion_Videos"


def _infer_product_metadata(file_name: str) -> Tuple[str, str, str, str, str]:
    """Derives commercial B2B YouTube metadata cleanly from a Drive video filename."""
    clean_base = file_name.rsplit(".", 1)[0].replace("_", " ").replace("-", " ").strip()
    lower = clean_base.lower()

    if "mozzarella" in lower or "milky" in lower:
        sku, prod = "DAIRY-004", "Milky Mist Diced Mozzarella (1kg & 2kg)"
    elif "soya" in lower or "meal time" in lower:
        sku, prod = "SAUCES-025", "Meal Time Dark Soya & Chilli Sauces"
    elif "jalapeno" in lower or "jalape" in lower:
        sku, prod = "SAUCES-010", "Del Monte Sliced Jalapeños (3kg Tin)"
    elif "panko" in lower:
        sku, prod = "SAUCES-024", "Golden Crown Panko Bread Crumbs (1kg)"
    elif "cream" in lower or "sudarshan" in lower:
        sku, prod = "DAIRY-009", "Sudarshan Dairy Fresh Cream (1L)"
    elif "fries" in lower or "potato" in lower:
        sku, prod = "VEG-001", "Commercial French Fries (6mm / 9mm)"
    elif "momo" in lower:
        sku, prod = "NONVEG-001", "Triken Frozen Momos (Chicken / Veg)"
    elif "butter paper" in lower or "ogr" in lower or "pizza box" in lower:
        sku, prod = "PACKAGING-001", "40 GSM OGR Butter Paper & Pizza Boxes"
    else:
        sku, prod = "RAIS-B2B", clean_base

    title = f"{clean_base} | RAIS Agencies Rayachoty Wholesale"[:100]
    desc = (
        f"Wholesale commercial supply of {prod} for cafes, pizzerias, bakeries & QSR kitchens in Rayachoty and Annamayya District.\n\n"
        f"Depot: {DEPOT_ADDRESS}\n"
        f"WhatsApp Trade Order: https://wa.me/91{DEPOT_PHONE}?text=Hi+RAIS+Agencies,+interested+in+{sku}\n"
        f"Routes: {CORRIDORS}"
    )
    tags = "RAISAgencies,Rayachoty,FrozenFoodWholesale,CafeSupplies,RestaurantSupplies,Shorts"
    return sku, prod, title, desc, tags


async def _get_drive_youtube_token(db: AsyncSession) -> Tuple[Optional[str], bool]:
    """Returns (valid_access_token, has_drive_and_youtube_scopes)."""
    token = await gbp_service.get_valid_access_token(db)
    if not token:
        return None, False
    stmt = select(GoogleConnection).order_by(GoogleConnection.id.desc()).limit(1)
    conn = (await db.execute(stmt)).scalar_one_or_none()
    scopes = (conn.scopes_granted or "") if conn else ""
    has_yt_drive = ("youtube" in scopes or "drive" in scopes)
    return token, has_yt_drive


async def _serialize_drive_settings(setting: YouTubeDriveSetting, db: AsyncSession) -> YouTubeDriveSettingRead:
    token, has_scopes = await _get_drive_youtube_token(db)
    gemini_key = await VideoAIService.resolve_gemini_key(db)
    return YouTubeDriveSettingRead(
        id=setting.id,
        folder_id=setting.folder_id,
        folder_name=setting.folder_name,
        auto_publish_daily=setting.auto_publish_daily,
        auto_publish_instagram=bool(setting.auto_publish_instagram),
        auto_publish_facebook=bool(setting.auto_publish_facebook),
        auto_post_immediately=True if setting.auto_post_immediately is None else bool(setting.auto_post_immediately),
        auto_first_comment=True if setting.auto_first_comment is None else bool(setting.auto_first_comment),
        gemini_connected=bool(gemini_key),
        daily_publish_hour=setting.daily_publish_hour,
        is_connected=setting.is_connected,
        oauth_connected=bool(token and has_scopes),
        last_synced_at=setting.last_synced_at
    )


@router.get("/settings", response_model=YouTubeDriveSettingRead, dependencies=[Depends(require_admin)])
async def get_settings(db: AsyncSession = Depends(get_db)):
    """Fetch current Google Drive folder configuration, Auto-Pilot toggles & OAuth connectivity."""
    stmt = select(YouTubeDriveSetting).limit(1)
    setting = (await db.execute(stmt)).scalar_one_or_none()
    if not setting:
        setting = YouTubeDriveSetting(
            folder_id=DEFAULT_DRIVE_FOLDER_ID,
            folder_name=DEFAULT_DRIVE_FOLDER_NAME,
            auto_publish_daily=True,
            auto_publish_instagram=True,
            auto_publish_facebook=True,
            auto_post_immediately=True,
            auto_first_comment=True,
            daily_publish_hour=10,
            is_connected=bool(DEFAULT_DRIVE_FOLDER_ID)
        )
        db.add(setting)
        await db.commit()
        await db.refresh(setting)
    elif not setting.folder_id:
        setting.folder_id = DEFAULT_DRIVE_FOLDER_ID
        setting.is_connected = True
        await db.commit()
        await db.refresh(setting)

    return await _serialize_drive_settings(setting, db)


@router.post("/settings", response_model=YouTubeDriveSettingRead, dependencies=[Depends(require_admin)])
async def update_settings(payload: YouTubeDriveSettingUpdate, db: AsyncSession = Depends(get_db)):
    """Update Google Drive folder ID, Gemini Video AI key & multi-platform auto-pilot preferences."""
    stmt = select(YouTubeDriveSetting).limit(1)
    setting = (await db.execute(stmt)).scalar_one_or_none()
    if not setting:
        setting = YouTubeDriveSetting(
            folder_id=DEFAULT_DRIVE_FOLDER_ID,
            folder_name=DEFAULT_DRIVE_FOLDER_NAME,
            is_connected=bool(DEFAULT_DRIVE_FOLDER_ID),
        )
        db.add(setting)

    if payload.folder_id is not None:
        clean_id = payload.folder_id.strip()
        if "drive.google.com" in clean_id and "folders/" in clean_id:
            clean_id = clean_id.split("folders/")[1].split("?")[0].split("/")[0]
        setting.folder_id = clean_id
        setting.is_connected = bool(clean_id)
    if payload.folder_name is not None:
        setting.folder_name = payload.folder_name
    if payload.auto_publish_daily is not None:
        setting.auto_publish_daily = payload.auto_publish_daily
    if payload.auto_publish_instagram is not None:
        setting.auto_publish_instagram = payload.auto_publish_instagram
    if payload.auto_publish_facebook is not None:
        setting.auto_publish_facebook = payload.auto_publish_facebook
    if payload.auto_post_immediately is not None:
        setting.auto_post_immediately = payload.auto_post_immediately
    if payload.auto_first_comment is not None:
        setting.auto_first_comment = payload.auto_first_comment
    if payload.gemini_api_key is not None:
        cleaned_key = payload.gemini_api_key.strip()
        setting.encrypted_gemini_api_key = encrypt_token(cleaned_key) if cleaned_key else None
    if payload.daily_publish_hour is not None:
        setting.daily_publish_hour = payload.daily_publish_hour

    setting.last_synced_at = datetime.datetime.now(datetime.timezone.utc)
    await db.commit()
    await db.refresh(setting)

    return await _serialize_drive_settings(setting, db)


@router.patch("/queue/{item_id}", response_model=YouTubeQueueItemRead, dependencies=[Depends(require_admin)])
async def update_queue_item(
    item_id: int, payload: YouTubeQueueItemUpdate, db: AsyncSession = Depends(get_db)
):
    """Update generated hook title, bilingual caption, hashtags, or first comment on a queued item."""
    item = (await db.execute(select(YouTubeQueueItem).where(YouTubeQueueItem.id == item_id))).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Queue item not found")

    if payload.product_sku is not None:
        item.product_sku = payload.product_sku
    if payload.product_name is not None:
        item.product_name = payload.product_name
    if payload.video_title is not None:
        item.video_title = payload.video_title[:150]
    if payload.description is not None:
        item.description = payload.description
    if payload.first_comment is not None:
        item.first_comment = payload.first_comment
    if payload.tags is not None:
        item.tags = payload.tags

    await db.commit()
    await db.refresh(item)
    return item


@router.post("/queue/{item_id}/analyze", response_model=YouTubeQueueItemRead, dependencies=[Depends(require_admin)])
async def analyze_queue_item_video(item_id: int, db: AsyncSession = Depends(get_db)):
    """Re-analyzes a queued Drive MP4 (using Gemini Video Vision if configured) and upgrades viral hook + comment."""
    item = (await db.execute(select(YouTubeQueueItem).where(YouTubeQueueItem.id == item_id))).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Queue item not found")

    gemini_key = await VideoAIService.resolve_gemini_key(db)
    video_bytes: Optional[bytes] = None
    if gemini_key and item.drive_file_id:
        try:
            video_bytes = await download_drive_video_bytes(item.drive_file_id, db)
        except Exception:
            video_bytes = None

    meta = await VideoAIService.analyze_drive_video(
        file_name=item.file_name,
        drive_description="",
        video_bytes=video_bytes,
        gemini_api_key=gemini_key,
    )
    item.product_sku = meta["product_sku"]
    item.product_name = meta["product_name"]
    item.video_title = meta["video_title"]
    item.description = meta["description"]
    item.first_comment = meta["first_comment"]
    item.tags = meta["tags"]
    item.ai_analyzed = bool(meta.get("ai_analyzed", False))
    await db.commit()
    await db.refresh(item)
    return item


@router.get("/queue", response_model=List[YouTubeQueueItemRead], dependencies=[Depends(require_admin)])
async def list_queue(db: AsyncSession = Depends(get_db)):
    """List all queued and published YouTube videos from real Drive syncs."""
    stmt = select(YouTubeQueueItem).order_by(YouTubeQueueItem.id.asc())
    res = await db.execute(stmt)
    return list(res.scalars().all())


@router.delete("/queue/clear", dependencies=[Depends(require_admin)])
async def clear_queue(db: AsyncSession = Depends(get_db)):
    """Wipes all items from the YouTube queue."""
    await db.execute(delete(YouTubeQueueItem))
    await db.commit()
    return {"status": "SUCCESS", "message": "Queue cleared completely."}


@router.delete("/queue/{item_id}", dependencies=[Depends(require_admin)])
async def delete_queue_item(item_id: int, db: AsyncSession = Depends(get_db)):
    """Deletes a single video entry from the multi-platform queue."""
    item = (
        await db.execute(select(YouTubeQueueItem).where(YouTubeQueueItem.id == item_id))
    ).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Queue item not found")
    await db.delete(item)
    await db.commit()
    return {"status": "DELETED", "id": item_id, "message": "Queue item removed."}


@router.post("/sync-drive", response_model=YouTubeSyncResult, dependencies=[Depends(require_admin)])
async def sync_google_drive(db: AsyncSession = Depends(get_db)):
    """
    Scans the configured Google Drive folder via Google Drive API v3 for MP4/MOV/WEBM files
    and enqueues new items for YouTube publishing.
    """
    setting = (await db.execute(select(YouTubeDriveSetting).limit(1))).scalar_one_or_none()
    folder_id = setting.folder_id if setting and setting.folder_id else DEFAULT_DRIVE_FOLDER_ID

    if setting:
        setting.last_synced_at = datetime.datetime.now(datetime.timezone.utc)
        await db.commit()

    token, has_scopes = await _get_drive_youtube_token(db)
    queued_items = list((await db.execute(select(YouTubeQueueItem).where(YouTubeQueueItem.status == YouTubeQueueStatus.QUEUED))).scalars().all())

    if not token or not has_scopes:
        return YouTubeSyncResult(
            status="SUCCESS",
            new_videos_found=0,
            total_queued=len(queued_items),
            message=(
                f"Drive folder '{folder_id}' saved, 0 files scanned: Google OAuth authorization with "
                "Google Drive & YouTube permissions is required to read live files."
            )
        )

    new_added = 0
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                "https://www.googleapis.com/drive/v3/files",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "q": f"'{folder_id}' in parents and trashed = false and mimeType contains 'video/'",
                    "fields": "files(id, name, description, mimeType, size, createdTime)",
                    "orderBy": "createdTime asc"
                }
            )
            if resp.status_code != 200:
                err_detail = resp.text[:250]
                return YouTubeSyncResult(
                    status="ERROR",
                    new_videos_found=0,
                    total_queued=len(queued_items),
                    message=f"Google Drive API error ({resp.status_code}): {err_detail}"
                )

            files = resp.json().get("files", [])
            existing_ids = set(
                (await db.execute(select(YouTubeQueueItem.drive_file_id))).scalars().all()
            )
            base_day = datetime.datetime.now(datetime.timezone.utc)
            gemini_key = await VideoAIService.resolve_gemini_key(db)

            for f in files:
                fid = f.get("id")
                fname = f.get("name", "promo_video.mp4")
                fdesc = f.get("description") or ""
                try:
                    fsize = int(f.get("size") or 0)
                except (TypeError, ValueError):
                    fsize = 0
                if not fid or fid in existing_ids:
                    continue

                video_bytes: Optional[bytes] = None
                if gemini_key and (fsize == 0 or fsize <= VideoAIService.MAX_INLINE_BYTES):
                    try:
                        dl = await client.get(
                            f"https://www.googleapis.com/drive/v3/files/{fid}?alt=media",
                            headers={"Authorization": f"Bearer {token}"},
                            timeout=60.0,
                        )
                        if dl.status_code == 200:
                            video_bytes = dl.content
                    except Exception:
                        video_bytes = None

                meta = await VideoAIService.analyze_drive_video(
                    file_name=fname,
                    drive_description=fdesc,
                    video_bytes=video_bytes,
                    gemini_api_key=gemini_key,
                )
                item = YouTubeQueueItem(
                    drive_file_id=fid,
                    file_name=fname,
                    product_sku=meta["product_sku"],
                    product_name=meta["product_name"],
                    video_title=meta["video_title"],
                    description=meta["description"],
                    first_comment=meta["first_comment"],
                    tags=meta["tags"],
                    ai_analyzed=bool(meta.get("ai_analyzed", False)),
                    status=YouTubeQueueStatus.QUEUED,
                    scheduled_for=base_day + datetime.timedelta(days=len(queued_items) + new_added)
                )
                db.add(item)
                existing_ids.add(fid)
                new_added += 1

            await db.commit()
    except Exception as e:
        return YouTubeSyncResult(
            status="ERROR",
            new_videos_found=0,
            total_queued=len(queued_items),
            message=f"Failed to scan Google Drive folder: {e}"
        )

    final_queued = list((await db.execute(select(YouTubeQueueItem).where(YouTubeQueueItem.status == YouTubeQueueStatus.QUEUED))).scalars().all())
    return YouTubeSyncResult(
        status="SUCCESS",
        new_videos_found=new_added,
        total_queued=len(final_queued),
        message=f"Scanned Google Drive folder: {new_added} new video(s) imported, {len(final_queued)} queued."
    )


async def download_drive_video_bytes(drive_file_id: str, db: AsyncSession) -> bytes:
    """Downloads genuine video bytes from Google Drive API v3 using stored OAuth token."""
    token, has_scopes = await _get_drive_youtube_token(db)
    if not token or not has_scopes:
        raise HTTPException(
            status_code=400,
            detail="Google OAuth authorization with Drive/YouTube scopes is required to fetch Drive videos."
        )
    async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
        drive_resp = await client.get(
            f"https://www.googleapis.com/drive/v3/files/{drive_file_id}?alt=media",
            headers={"Authorization": f"Bearer {token}"}
        )
        if drive_resp.status_code != 200:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to download video from Google Drive ({drive_resp.status_code})."
            )
        return drive_resp.content


async def _upload_drive_file_to_youtube(item: YouTubeQueueItem, db: AsyncSession) -> YouTubePublishResult:
    """Downloads genuine video bytes from Google Drive and uploads to YouTube Data API v3."""
    token, has_scopes = await _get_drive_youtube_token(db)
    if not token or not has_scopes:
        raise HTTPException(
            status_code=400,
            detail="Google OAuth authorization with YouTube Data API v3 & Drive scopes is required before publishing."
        )
    if not item.drive_file_id:
        raise HTTPException(
            status_code=400,
            detail="Queued item has no authentic Google Drive file ID. Sync directly from Drive first."
        )

    tag_list = [t.strip() for t in (item.tags or "").split(",") if t.strip()]
    metadata = {
        "snippet": {
            "title": item.video_title[:100],
            "description": item.description,
            "tags": tag_list,
            "categoryId": "22"
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False
        }
    }

    try:
        video_bytes = await download_drive_video_bytes(item.drive_file_id, db)
    except HTTPException:
        item.status = YouTubeQueueStatus.FAILED
        await db.commit()
        raise

    async with httpx.AsyncClient(timeout=120.0) as client:

        # 2. Initiate YouTube resumable upload
        init_resp = await client.post(
            "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Length": str(len(video_bytes)),
                "X-Upload-Content-Type": "video/mp4"
            },
            content=json.dumps(metadata)
        )
        if init_resp.status_code not in (200, 201) or not init_resp.headers.get("Location"):
            item.status = YouTubeQueueStatus.FAILED
            await db.commit()
            raise HTTPException(
                status_code=400,
                detail=f"YouTube upload initiation rejected ({init_resp.status_code}): {init_resp.text[:250]}"
            )

        upload_url = init_resp.headers["Location"]
        up_resp = await client.put(
            upload_url,
            headers={"Content-Type": "video/mp4"},
            content=video_bytes
        )
        if up_resp.status_code not in (200, 201):
            item.status = YouTubeQueueStatus.FAILED
            await db.commit()
            raise HTTPException(
                status_code=400,
                detail=f"YouTube upload failed ({up_resp.status_code}): {up_resp.text[:250]}"
            )

        yt_data = up_resp.json()
        yt_id = yt_data.get("id")
        if not yt_id:
            raise HTTPException(status_code=500, detail="YouTube API response did not include a video ID.")

        now = datetime.datetime.now(datetime.timezone.utc)
        item.status = YouTubeQueueStatus.PUBLISHED
        item.published_at = now
        item.youtube_video_id = yt_id
        item.youtube_url = f"https://youtube.com/shorts/{yt_id}"
        await db.commit()
        await db.refresh(item)

        return YouTubePublishResult(
            status="SUCCESS",
            video_id=item.id,
            youtube_video_id=item.youtube_video_id,
            youtube_url=item.youtube_url,
            video_title=item.video_title,
            message=f"Successfully published '{item.video_title}' to YouTube! Live link: {item.youtube_url}"
        )


@router.post("/publish-next", response_model=YouTubePublishResult, dependencies=[Depends(require_admin)])
async def publish_next_video(db: AsyncSession = Depends(get_db)):
    """Uploads the next genuinely queued Drive video to YouTube via YouTube Data API v3."""
    stmt = (
        select(YouTubeQueueItem)
        .where(YouTubeQueueItem.status == YouTubeQueueStatus.QUEUED)
        .order_by(YouTubeQueueItem.id.asc())
        .limit(1)
    )
    next_item = (await db.execute(stmt)).scalar_one_or_none()
    if not next_item:
        return YouTubePublishResult(
            status="ALL_CAUGHT_UP",
            message="No pending videos in queue. Drop promotion videos into your Google Drive folder and sync."
        )
    return await _upload_drive_file_to_youtube(next_item, db)


@router.post("/publish-item/{item_id}", response_model=YouTubePublishResult, dependencies=[Depends(require_admin)])
async def publish_specific_item(item_id: int, db: AsyncSession = Depends(get_db)):
    """Immediately uploads a specific queued Drive video to YouTube Data API v3."""
    item = (await db.execute(select(YouTubeQueueItem).where(YouTubeQueueItem.id == item_id))).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Queue item not found")
    return await _upload_drive_file_to_youtube(item, db)


@router.get("/download-drive/{drive_file_id}", dependencies=[Depends(require_admin)])
async def download_drive_video_for_share(drive_file_id: str, db: AsyncSession = Depends(get_db)):
    """
    Streams an authentic Google Drive MP4 video so WhatsApp Status (via mobile navigator.share)
    or local download works safely without risky unofficial WhatsApp Web bots.
    """
    item = (
        await db.execute(
            select(YouTubeQueueItem).where(YouTubeQueueItem.drive_file_id == drive_file_id).limit(1)
        )
    ).scalar_one_or_none()
    raw_name = item.file_name if item and item.file_name else f"rais_promo_{drive_file_id}.mp4"
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", raw_name)
    if not safe_name.lower().endswith(".mp4"):
        safe_name = f"{safe_name}.mp4"

    video_bytes = await download_drive_video_bytes(drive_file_id, db)
    return Response(
        content=video_bytes,
        media_type="video/mp4",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}"',
            "Content-Length": str(len(video_bytes)),
            "Cache-Control": "no-store",
        },
    )


async def _dispatch_item_to_channels(
    item: YouTubeQueueItem,
    targets: List[str],
    db: AsyncSession,
) -> Dict[str, Any]:
    """Shared cross-platform dispatcher across YouTube Shorts, Instagram Reels & Facebook Page (+ First Comments)."""
    results: Dict[str, Any] = {}
    errors: List[str] = []

    if "youtube" in targets and item.status != YouTubeQueueStatus.PUBLISHED:
        try:
            yt_res = await _upload_drive_file_to_youtube(item, db)
            results["youtube"] = {
                "youtube_video_id": yt_res.youtube_video_id,
                "youtube_url": yt_res.youtube_url,
                "message": yt_res.message,
            }
        except HTTPException as exc:
            errors.append(f"YouTube: {exc.detail}")
        except Exception as exc:
            errors.append(f"YouTube: {exc}")

    meta_targets: List[str] = []
    if "instagram" in targets and item.ig_status != "PUBLISHED":
        meta_targets.append("instagram")
    if "facebook" in targets and item.fb_status != "PUBLISHED":
        meta_targets.append("facebook")

    if meta_targets:
        try:
            meta_out = await MetaService.publish_queue_item(
                db=db,
                item=item,
                platforms=meta_targets,
                download_bytes_fn=download_drive_video_bytes,
                base_url=settings.BACKEND_PUBLIC_URL or None,
            )
            results.update(meta_out.get("results") or {})
            errors.extend(meta_out.get("errors") or [])
        except (ValueError, RuntimeError) as exc:
            errors.append(str(exc))

    await db.refresh(item)
    return {"results": results, "errors": errors}


def _resolve_enabled_channels(setting: Optional[YouTubeDriveSetting]) -> List[str]:
    targets: List[str] = []
    if not setting or setting.auto_publish_daily:
        targets.append("youtube")
    if not setting or setting.auto_publish_instagram:
        targets.append("instagram")
    if not setting or setting.auto_publish_facebook:
        targets.append("facebook")
    return targets or ["youtube", "instagram", "facebook"]


async def run_autopilot_cycle(db: AsyncSession) -> Dict[str, Any]:
    """
    Zero-manual full automation cycle:
    1) Checks Emergency Kill Switch.
    2) Scans Google Drive for newly uploaded videos and runs VideoAIService hook/caption/comment generation.
    3) In Instant Auto-Pilot (auto_post_immediately=True), publishes pending items immediately;
       in Daily Cadence Mode (auto_post_immediately=False), publishes 1 video per day once daily_publish_hour (IST) arrives.
    4) When live Google Business Profile API is enabled (USE_MOCK_GBP=False), syncs GBP reviews & due campaign posts.
    """
    if await SchedulerService().check_kill_switch(db):
        return {
            "status": "HALTED",
            "message": "Emergency kill switch is active. Auto-publish paused.",
            "new_videos_found": 0,
            "published_items": [],
            "errors": [],
        }

    # Optional cloud GBP sync & scheduled post execution (never fires in mock/demo mode)
    if not settings.USE_MOCK_GBP:
        try:
            from app.services.review_service import review_service
            await review_service.sync_reviews_from_gbp(db)
            await SchedulerService().execute_publishing_cycle(db)
        except Exception:
            pass

    sync_res = await sync_google_drive(db)
    setting = (await db.execute(select(YouTubeDriveSetting).limit(1))).scalar_one_or_none()
    auto_immediate = True if not setting or setting.auto_post_immediately is None else bool(setting.auto_post_immediately)
    daily_enabled = True if not setting or setting.auto_publish_daily is None else bool(setting.auto_publish_daily)

    all_items = list(
        (await db.execute(select(YouTubeQueueItem).order_by(YouTubeQueueItem.id.asc()))).scalars().all()
    )

    if not auto_immediate:
        if not daily_enabled:
            return {
                "status": "SYNCED_ONLY",
                "message": sync_res.message,
                "new_videos_found": sync_res.new_videos_found,
                "published_items": [],
                "errors": [],
            }
        ist_offset = datetime.timedelta(hours=5, minutes=30)
        ist_now = datetime.datetime.now(datetime.timezone.utc) + ist_offset
        target_hour = setting.daily_publish_hour if setting and setting.daily_publish_hour is not None else 10
        today_ist = ist_now.date()

        def _was_published_today(it: YouTubeQueueItem) -> bool:
            for ts in (it.published_at, it.ig_published_at, it.fb_published_at):
                if ts is not None:
                    ts_aware = ts if ts.tzinfo is not None else ts.replace(tzinfo=datetime.timezone.utc)
                    if (ts_aware + ist_offset).date() == today_ist:
                        return True
            return False

        if ist_now.hour < target_hour or any(_was_published_today(it) for it in all_items):
            return {
                "status": "SYNCED_ONLY",
                "message": (
                    f"{sync_res.message} Daily cadence scheduled for {target_hour:02d}:00 IST "
                    f"(current IST: {ist_now.strftime('%H:%M')})."
                ),
                "new_videos_found": sync_res.new_videos_found,
                "published_items": [],
                "errors": [],
            }

    targets = _resolve_enabled_channels(setting)
    token, has_scopes = await _get_drive_youtube_token(db)
    meta_creds = await MetaService.get_credentials(db)

    runnable_targets: List[str] = []
    if "youtube" in targets and token and has_scopes:
        runnable_targets.append("youtube")
    if ("instagram" in targets or "facebook" in targets) and meta_creds and token and has_scopes:
        if "instagram" in targets:
            runnable_targets.append("instagram")
        if "facebook" in targets:
            runnable_targets.append("facebook")

    if not runnable_targets:
        return {
            "status": "AUTH_REQUIRED",
            "message": sync_res.message,
            "new_videos_found": sync_res.new_videos_found,
            "published_items": [],
            "errors": [],
        }

    published_items: List[Dict[str, Any]] = []
    errors: List[str] = []
    max_per_cycle = len(all_items) if auto_immediate else 1

    for item in all_items:
        needs_yt = "youtube" in runnable_targets and item.status == YouTubeQueueStatus.QUEUED
        needs_ig = "instagram" in runnable_targets and (item.ig_status or "PENDING") == "PENDING"
        needs_fb = "facebook" in runnable_targets and (item.fb_status or "PENDING") == "PENDING"
        if not (needs_yt or needs_ig or needs_fb):
            continue

        item_targets = [
            t for t, need in (("youtube", needs_yt), ("instagram", needs_ig), ("facebook", needs_fb)) if need
        ]
        outcome = await _dispatch_item_to_channels(item, item_targets, db)
        if outcome["results"]:
            published_items.append({"item_id": item.id, "title": item.video_title, "results": outcome["results"]})
        if outcome["errors"]:
            errors.extend([f"#{item.id}: {e}" for e in outcome["errors"]])
        if len(published_items) >= max_per_cycle:
            break

    return {
        "status": "PARTIAL" if (errors and published_items) else ("ERROR" if errors else "SUCCESS"),
        "new_videos_found": sync_res.new_videos_found,
        "published_count": len(published_items),
        "published_items": published_items,
        "errors": errors,
        "message": (
            f"Auto-Pilot complete: {sync_res.new_videos_found} new Drive video(s), "
            f"{len(published_items)} item(s) published across {', '.join(runnable_targets)}."
        ),
    }


_autopilot_locks: "WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock]" = WeakKeyDictionary()


def _get_autopilot_lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    lock = _autopilot_locks.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        _autopilot_locks[loop] = lock
    return lock


async def _run_autopilot_locked(db: AsyncSession) -> Dict[str, Any]:
    lock = _get_autopilot_lock()
    if lock.locked():
        return {
            "status": "ALREADY_RUNNING",
            "message": "Auto-Pilot cycle is already executing in background.",
            "new_videos_found": 0,
            "published_items": [],
            "errors": [],
        }
    async with lock:
        return await run_autopilot_cycle(db)


async def _run_autopilot_background_task() -> None:
    try:
        async with AsyncSessionLocal() as bg_db:
            await _run_autopilot_locked(bg_db)
    except Exception:
        pass


@router.api_route("/auto-run", methods=["GET", "POST"], dependencies=[Depends(verify_cron_or_admin)])
async def trigger_autopilot_run(
    background: bool = Query(
        default=False,
        description="Set true for external cron triggers (e.g. cron-job.org) so HTTP responds immediately while publishing runs asynchronously.",
    ),
    db: AsyncSession = Depends(get_db),
):
    """Runs the full hands-free Drive Scan -> AI Hook/Comment Generation -> Multi-Platform Publish cycle."""
    if background:
        lock = _get_autopilot_lock()
        if lock.locked():
            return {
                "status": "ALREADY_RUNNING",
                "message": "Auto-Pilot cycle is already running in background.",
            }
        asyncio.create_task(_run_autopilot_background_task())
        return {
            "status": "SCHEDULED_IN_BACKGROUND",
            "message": "Drive Auto-Pilot scan & publish started asynchronously.",
        }
    return await _run_autopilot_locked(db)


@router.post("/publish-multi/{item_id}", dependencies=[Depends(require_admin)])
async def publish_item_multi_platform(
    item_id: int,
    payload: Optional[MetaPublishRequest] = Body(default=None),
    db: AsyncSession = Depends(get_db),
):
    """
    Unified cross-platform publisher: dispatches one synced Drive video to selected channels
    among YouTube Shorts, Instagram Reels (@rais_agencies_frozen_foods), and Facebook Page (+ First Comments).
    """
    item = (await db.execute(select(YouTubeQueueItem).where(YouTubeQueueItem.id == item_id))).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Queue item not found")

    if payload and payload.platforms:
        targets = [p.strip().lower() for p in payload.platforms if p and p.strip()]
    else:
        setting = (await db.execute(select(YouTubeDriveSetting).limit(1))).scalar_one_or_none()
        targets = _resolve_enabled_channels(setting)

    outcome = await _dispatch_item_to_channels(item, targets, db)
    results = outcome["results"]
    errors = outcome["errors"]

    if errors and not results:
        raise HTTPException(status_code=400, detail=" | ".join(errors))

    return {
        "status": "PARTIAL" if errors else "SUCCESS",
        "item_id": item.id,
        "results": results,
        "errors": errors,
        "item": YouTubeQueueItemRead.model_validate(item).model_dump(mode="json"),
    }


@router.get("/setup-guide", dependencies=[Depends(require_admin)])
async def get_setup_guide():
    """Returns official step-by-step setup instructions for Google Cloud Console and Drive."""
    return {
        "step_1_enable_apis": {
            "title": "Enable Google Drive API & YouTube Data API v3",
            "instructions": [
                "Go to Google Cloud Console (https://console.cloud.google.com).",
                "Select your RAIS project in the top bar.",
                "In the left menu, navigate to 'APIs & Services' -> 'Library'.",
                "Search for 'Google Drive API' and click 'Enable'.",
                "Search for 'YouTube Data API v3' and click 'Enable'."
            ]
        },
        "step_2_get_folder_id": {
            "title": "Get Your Google Drive Folder ID",
            "instructions": [
                "Open Google Drive (https://drive.google.com).",
                "Create or open your folder named 'RAIS_Daily_Promotion_Videos'.",
                "Copy the Folder ID after 'folders/' in the URL and save it in Drive Folder Integration."
            ]
        },
        "step_3_oauth_credentials": {
            "title": "OAuth 2.0 Credentials & YouTube Channel",
            "instructions": [
                "Under 'APIs & Services' -> 'Credentials', verify your OAuth 2.0 Web Client has Authorized redirect URI: https://rais-growth-backend.onrender.com/api/v1/google/callback",
                "Authorize with the Google account managing your RAIS Agencies YouTube channel."
            ]
        }
    }
