from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_admin
from app.models.entities import AnalyticsEvent, YouTubeQueueItem, YouTubeQueueStatus
from app.services.gbp_service import gbp_service
from app.services.meta_service import MetaService

router = APIRouter(prefix="/analytics", tags=["Live Storefront & Social Analytics"])

_ALLOWED_EVENTS = {
    "PAGE_VIEW",
    "PRODUCT_VIEW",
    "WHATSAPP_CLICK",
    "CATALOGUE_OPEN",
    "QUOTE_ADD",
    "BROCHURE_DOWNLOAD",
}


class TrackEventPayload(BaseModel):
    event_type: str = Field(..., max_length=50)
    path: str = Field(default="/", max_length=255)
    source: str = Field(default="Google / Direct", max_length=80)
    sku: Optional[str] = Field(default=None, max_length=80)
    product_name: Optional[str] = Field(default=None, max_length=200)
    visitor_id: Optional[str] = Field(default=None, max_length=120)


@router.post("/track")
async def track_storefront_event(
    payload: TrackEventPayload,
    db: AsyncSession = Depends(get_db),
):
    """Public anonymous event ingestion endpoint storing multi-device storefront interactions in Neon Postgres."""
    ev_type = payload.event_type.strip().upper()
    if ev_type not in _ALLOWED_EVENTS:
        ev_type = "PAGE_VIEW"

    ev = AnalyticsEvent(
        event_type=ev_type,
        path=payload.path[:255],
        source=payload.source[:80],
        sku=payload.sku[:80] if payload.sku else None,
        product_name=payload.product_name[:200] if payload.product_name else None,
        visitor_id=payload.visitor_id[:120] if payload.visitor_id else None,
    )
    db.add(ev)
    await db.commit()
    return {"status": "RECORDED"}


@router.get("/summary", dependencies=[Depends(require_admin)])
async def get_analytics_summary(
    days: int = 30,
    db: AsyncSession = Depends(get_db),
):
    """Aggregates genuine cross-device storefront visitor & product metrics from Neon Postgres."""
    since = datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 365)))
    rows = list(
        (
            await db.execute(
                select(AnalyticsEvent)
                .where(AnalyticsEvent.created_at >= since)
                .order_by(AnalyticsEvent.created_at.desc())
            )
        )
        .scalars()
        .all()
    )

    by_type = Counter(r.event_type for r in rows)
    by_source = Counter(r.source for r in rows)
    by_product = Counter(r.product_name for r in rows if r.product_name)
    unique_visitors = len({r.visitor_id for r in rows if r.visitor_id})

    return {
        "source": "Neon Postgres Live Telemetry",
        "window_days": days,
        "total_events": len(rows),
        "unique_visitors": unique_visitors,
        "page_views": by_type.get("PAGE_VIEW", 0),
        "catalogue_opens": by_type.get("CATALOGUE_OPEN", 0),
        "whatsapp_clicks": by_type.get("WHATSAPP_CLICK", 0),
        "quote_adds": by_type.get("QUOTE_ADD", 0),
        "sources": dict(by_source),
        "top_products": [{"name": name, "count": cnt} for name, cnt in by_product.most_common(5)],
        "recent_events": [
            {
                "id": r.id,
                "event_type": r.event_type,
                "path": r.path,
                "source": r.source,
                "sku": r.sku,
                "product_name": r.product_name,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows[:25]
        ],
    }


@router.get("/social", dependencies=[Depends(require_admin)])
async def get_live_social_performance(db: AsyncSession = Depends(get_db)):
    """
    Pulls genuine per-video live statistics directly from YouTube Data API v3
    and Meta Graph API v21.0 (Instagram Reels + Facebook Page Videos) for every published Drive item.
    """
    items = list(
        (await db.execute(select(YouTubeQueueItem).order_by(YouTubeQueueItem.id.desc())))
        .scalars()
        .all()
    )
    meta_creds = await MetaService.get_credentials(db)
    google_token = await gbp_service.get_valid_access_token(db)

    yt_ids = [it.youtube_video_id for it in items if it.youtube_video_id and it.status == YouTubeQueueStatus.PUBLISHED]
    yt_stats_map: Dict[str, Dict[str, int]] = {}
    yt_note: Optional[str] = None

    async with httpx.AsyncClient(timeout=15.0) as client:
        if yt_ids and google_token:
            try:
                y_resp = await client.get(
                    "https://www.googleapis.com/youtube/v3/videos",
                    headers={"Authorization": f"Bearer {google_token}"},
                    params={"part": "statistics", "id": ",".join(yt_ids[:25])},
                )
                if y_resp.status_code == 200:
                    for v in y_resp.json().get("items", []):
                        st = v.get("statistics", {})
                        yt_stats_map[str(v["id"])] = {
                            "views": int(st.get("viewCount") or 0),
                            "likes": int(st.get("likeCount") or 0),
                            "comments": int(st.get("commentCount") or 0),
                        }
                else:
                    yt_note = f"YouTube statistics read returned HTTP {y_resp.status_code}"
            except Exception as exc:
                yt_note = str(exc)

        video_metrics: List[Dict[str, Any]] = []
        total_yt_views = 0
        total_ig_likes = 0
        total_ig_comments = 0
        total_fb_views = 0

        for it in items:
            if (
                it.status != YouTubeQueueStatus.PUBLISHED
                and it.ig_status != "PUBLISHED"
                and it.fb_status != "PUBLISHED"
            ):
                continue

            yt_stat = yt_stats_map.get(it.youtube_video_id or "")
            if yt_stat:
                total_yt_views += yt_stat["views"]

            ig_stat: Optional[Dict[str, Any]] = None
            if it.ig_media_id and meta_creds and meta_creds.get("access_token"):
                try:
                    ig_resp = await client.get(
                        f"{MetaService.GRAPH_BASE}/{it.ig_media_id}",
                        params={
                            "fields": "like_count,comments_count,permalink",
                            "access_token": meta_creds["access_token"],
                        },
                    )
                    if ig_resp.status_code == 200:
                        d = ig_resp.json()
                        likes = int(d.get("like_count") or 0)
                        comments = int(d.get("comments_count") or 0)
                        total_ig_likes += likes
                        total_ig_comments += comments
                        ig_stat = {"likes": likes, "comments": comments, "plays": None}
                        # Optional insights plays/reach
                        ins_resp = await client.get(
                            f"{MetaService.GRAPH_BASE}/{it.ig_media_id}/insights",
                            params={"metric": "plays,reach", "access_token": meta_creds["access_token"]},
                        )
                        if ins_resp.status_code == 200:
                            for m in ins_resp.json().get("data", []):
                                vals = m.get("values") or []
                                val = int(vals[0].get("value") or 0) if vals else 0
                                if m.get("name") == "plays":
                                    ig_stat["plays"] = val
                                elif m.get("name") == "reach":
                                    ig_stat["reach"] = val
                except Exception:
                    pass

            fb_stat: Optional[Dict[str, Any]] = None
            if it.fb_video_id and meta_creds and meta_creds.get("access_token"):
                try:
                    fb_resp = await client.get(
                        f"{MetaService.GRAPH_BASE}/{it.fb_video_id}",
                        params={
                            "fields": "views,likes.summary(true),comments.summary(true)",
                            "access_token": meta_creds["access_token"],
                        },
                    )
                    if fb_resp.status_code == 200:
                        fd = fb_resp.json()
                        views = int(fd.get("views") or 0)
                        total_fb_views += views
                        fb_stat = {
                            "views": views,
                            "likes": int((fd.get("likes") or {}).get("summary", {}).get("total_count") or 0),
                            "comments": int((fd.get("comments") or {}).get("summary", {}).get("total_count") or 0),
                        }
                except Exception:
                    pass

            video_metrics.append(
                {
                    "id": it.id,
                    "video_title": it.video_title,
                    "product_name": it.product_name,
                    "youtube_url": it.youtube_url,
                    "ig_url": it.ig_url,
                    "fb_url": it.fb_url,
                    "published_at": it.published_at.isoformat() if it.published_at else None,
                    "youtube": yt_stat,
                    "instagram": ig_stat,
                    "facebook": fb_stat,
                }
            )

    return {
        "source": "YouTube Data API v3 & Meta Graph API v21.0",
        "yt_telemetry_note": yt_note,
        "summary": {
            "published_videos": len(video_metrics),
            "youtube_views": total_yt_views,
            "instagram_likes": total_ig_likes,
            "instagram_comments": total_ig_comments,
            "facebook_views": total_fb_views,
        },
        "videos": video_metrics,
    }
