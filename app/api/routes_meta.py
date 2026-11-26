from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes_youtube import download_drive_video_bytes
from app.core.config import settings
from app.core.database import get_db
from app.core.security import require_admin
from app.models.entities import YouTubeQueueItem
from app.schemas.schemas import (
    MetaConnectRequest,
    MetaPublishRequest,
    MetaStatusResponse,
    YouTubeQueueItemRead,
)
from app.services.meta_service import MetaService

router = APIRouter(prefix="/meta", tags=["Meta Graph API (Instagram & Facebook)"])


@router.get("/status", response_model=MetaStatusResponse, dependencies=[Depends(require_admin)])
async def get_meta_status(db: AsyncSession = Depends(get_db)):
    """Returns genuine Meta Graph API connection status for linked Facebook Page & Instagram Business Account."""
    return await MetaService.get_status(db)


@router.post("/connect", response_model=MetaStatusResponse, dependencies=[Depends(require_admin)])
async def connect_meta_account(
    payload: MetaConnectRequest, db: AsyncSession = Depends(get_db)
):
    """Verifies a Meta User or Page Access Token live against Graph API v21.0 and stores it encrypted."""
    try:
        return await MetaService.verify_and_connect(
            db=db,
            access_token=payload.access_token,
            page_id=payload.page_id,
            ig_user_id=payload.ig_user_id,
        )
    except (ValueError, httpx.HTTPError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/disconnect", dependencies=[Depends(require_admin)])
async def disconnect_meta_account(db: AsyncSession = Depends(get_db)):
    """Clears stored Meta Page Access Token credentials from the local database."""
    await MetaService.disconnect(db)
    return {
        "status": "DISCONNECTED",
        "connected": False,
        "message": "Meta Facebook Page & Instagram connection cleared.",
    }


@router.get("/media-stream/{drive_file_id}")
async def stream_drive_video_for_meta(
    drive_file_id: str,
    exp: int = Query(..., description="Unix expiry timestamp"),
    sig: str = Query(..., description="HMAC-SHA256 signature"),
    db: AsyncSession = Depends(get_db),
):
    """
    HMAC-signed MP4 streaming endpoint used strictly by Meta's Instagram Reels ingestion servers
    to pull private Google Drive videos securely without exposing OAuth tokens.
    """
    if not MetaService.verify_media_signature(drive_file_id, exp, sig):
        raise HTTPException(
            status_code=403, detail="Invalid or expired Meta media stream signature."
        )

    video_bytes = await download_drive_video_bytes(drive_file_id, db)
    return Response(
        content=video_bytes,
        media_type="video/mp4",
        headers={
            "Content-Length": str(len(video_bytes)),
            "Accept-Ranges": "bytes",
            "Cache-Control": "private, max-age=300",
        },
    )


@router.post("/publish-item/{item_id}", dependencies=[Depends(require_admin)])
async def publish_drive_item_to_meta(
    item_id: int,
    payload: Optional[MetaPublishRequest] = Body(default=None),
    db: AsyncSession = Depends(get_db),
):
    """
    Publishes a synced Google Drive video item directly to Instagram Reels and/or Facebook Page
    using real Meta Graph API v21.0 endpoints.
    """
    item = (
        await db.execute(select(YouTubeQueueItem).where(YouTubeQueueItem.id == item_id))
    ).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Queue item not found")

    platforms = payload.platforms if payload else ["instagram", "facebook"]
    try:
        outcome = await MetaService.publish_queue_item(
            db=db,
            item=item,
            platforms=platforms,
            download_bytes_fn=download_drive_video_bytes,
            base_url=settings.BACKEND_PUBLIC_URL or None,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        **outcome,
        "item": YouTubeQueueItemRead.model_validate(item).model_dump(mode="json"),
    }


@router.get("/setup-guide", dependencies=[Depends(require_admin)])
async def get_meta_setup_guide():
    """Returns exact steps to generate a Meta Page Access Token for the linked FB Page + @rais_agencies_frozen_foods IG."""
    return {
        "step_1_app": {
            "title": "Create or Open Meta Business App (developers.facebook.com)",
            "instructions": [
                "Open https://developers.facebook.com/apps and sign in with the Facebook account that manages the RAIS Agencies Facebook Page.",
                "Click Create App -> Other -> Business (or open your existing Business App).",
                "No website privacy audit is needed for personal admin Mode (Development Mode works immediately for pages you own)."
            ],
        },
        "step_2_permissions": {
            "title": "Generate Token in Meta Graph API Explorer",
            "instructions": [
                "Open https://developers.facebook.com/tools/explorer/.",
                "Select your Meta App in the top-right dropdown.",
                "Under 'User or Page', click 'Get Token' -> 'Get Page Access Token'.",
                "Grant these 6 permissions: pages_show_list, pages_read_engagement, pages_manage_posts, pages_manage_engagement (for auto first comments on FB), instagram_basic, instagram_content_publish.",
                "Select your RAIS Agencies Facebook Page (linked to @rais_agencies_frozen_foods Instagram)."
            ],
        },
        "step_3_connect": {
            "title": "Paste Token Here & Auto-Discover Linked IG + FB",
            "instructions": [
                "Copy the generated Access Token from Graph API Explorer.",
                "Tip: Use Meta Access Token Debugger -> 'Extend Access Token' so it stays valid for ~60 days instead of 1 hour.",
                "Paste the token in the 'Connect Meta Account' box — we automatically verify & detect both your Facebook Page and linked Instagram Business Account."
            ],
        },
    }
