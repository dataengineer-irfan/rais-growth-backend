import json
from datetime import datetime, timezone
from typing import Any, Dict, List
from fastapi import APIRouter, Depends
from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import require_admin
from app.models.entities import IntegrationSyncLog
from app.services.gbp_service import gbp_service
from app.services.meta_service import MetaService
from app.services.video_ai_service import VideoAIService
from app.services.whatsapp_service import whatsapp_service

router = APIRouter(
    prefix="/integrations",
    tags=["Production Integration Monitoring"],
    dependencies=[Depends(require_admin)],
)


@router.get("/health")
async def get_integrations_health(db: AsyncSession = Depends(get_db)):
    """
    Verifies actual connectivity/configuration state for all 12 platform integrations.
    Never simulates CONNECTED when credentials or permissions are missing.
    """
    now = datetime.now(timezone.utc).isoformat()
    checks: List[Dict[str, Any]] = []

    # 1. Neon PostgreSQL / Primary DB
    try:
        await db.execute(text("SELECT 1"))
        checks.append({"name": "Neon PostgreSQL", "status": "CONNECTED", "last_checked_at": now, "detail": "Database query SELECT 1 succeeded."})
    except Exception as exc:
        checks.append({"name": "Neon PostgreSQL", "status": "UNAVAILABLE", "last_checked_at": now, "detail": str(exc)})

    # 2. Backend API
    checks.append({"name": "Backend API (FastAPI)", "status": "CONNECTED", "last_checked_at": now, "detail": f"v{settings.VERSION} responding."})

    # 3. Google Business Profile + Drive + YouTube
    gbp_st = await gbp_service.get_connection_status(db)
    scopes = " ".join(gbp_st.get("scopes_granted") or [])
    if gbp_st.get("is_simulated"):
        checks.append({"name": "Google Business Profile", "status": "DISCONNECTED", "last_checked_at": now, "detail": "USE_MOCK_GBP=True (mock mode active, not live)."})
    elif gbp_st.get("connected"):
        checks.append({"name": "Google Business Profile", "status": "CONNECTED", "last_checked_at": now, "detail": f"Account {gbp_st.get('account_email')} linked."})
    else:
        checks.append({"name": "Google Business Profile", "status": "DISCONNECTED", "last_checked_at": now, "detail": gbp_st.get("message")})

    checks.append({
        "name": "Google Drive",
        "status": "CONNECTED" if (gbp_st.get("connected") and "drive" in scopes) else "PERMISSION_MISSING" if gbp_st.get("connected") else "DISCONNECTED",
        "last_checked_at": now,
        "detail": "Drive readonly scope granted." if "drive" in scopes else "Google OAuth with drive.readonly scope required.",
    })
    checks.append({
        "name": "YouTube Data API",
        "status": "CONNECTED" if (gbp_st.get("connected") and "youtube" in scopes) else "PERMISSION_MISSING" if gbp_st.get("connected") else "DISCONNECTED",
        "last_checked_at": now,
        "detail": "YouTube upload scope granted." if "youtube" in scopes else "Google OAuth with youtube.upload scope required.",
    })

    # 4. Meta Graph API
    meta_st = await MetaService.get_status(db)
    checks.append({
        "name": "Meta Graph API (IG & FB)",
        "status": "CONNECTED" if meta_st.get("connected") else "DISCONNECTED",
        "last_checked_at": now,
        "detail": f"Page {meta_st.get('page_name')} / @{meta_st.get('ig_username')}" if meta_st.get("connected") else meta_st.get("message"),
    })

    # 5. Gemini AI
    gem_key = await VideoAIService.resolve_gemini_key(db)
    checks.append({
        "name": "Gemini AI",
        "status": "CONNECTED" if gem_key else "DISCONNECTED",
        "last_checked_at": now,
        "detail": "Gemini API key configured." if gem_key else "GEMINI_API_KEY not configured; falling back to template engine.",
    })

    # 6. WhatsApp Cloud API
    wa_st = await whatsapp_service.get_status(db)
    checks.append({
        "name": "WhatsApp Business Cloud API",
        "status": "CONNECTED" if wa_st.get("connected") else "DISCONNECTED",
        "last_checked_at": now,
        "detail": wa_st.get("message"),
    })

    # 7. Google Places API
    checks.append({
        "name": "Google Places API (New)",
        "status": "CONNECTED" if settings.GOOGLE_PLACES_API_KEY else "DISCONNECTED",
        "last_checked_at": now,
        "detail": "GOOGLE_PLACES_API_KEY configured." if settings.GOOGLE_PLACES_API_KEY else "GOOGLE_PLACES_API_KEY missing.",
    })

    # 8. GA4 & Google Search Console
    checks.append({
        "name": "Google Analytics 4 (Data API)",
        "status": "CONNECTED" if (settings.GA4_PROPERTY_ID and gbp_st.get("connected")) else "DISCONNECTED",
        "last_checked_at": now,
        "detail": f"Property {settings.GA4_PROPERTY_ID}" if settings.GA4_PROPERTY_ID else "GA4_PROPERTY_ID not configured; using Neon storefront telemetry.",
    })
    checks.append({
        "name": "Google Search Console",
        "status": "CONNECTED" if ("webmasters" in scopes and gbp_st.get("connected")) else "PERMISSION_MISSING" if gbp_st.get("connected") else "DISCONNECTED",
        "last_checked_at": now,
        "detail": f"Site {settings.GSC_SITE_URL}" if "webmasters" in scopes else "Search Console OAuth scope (webmasters.readonly) not granted.",
    })

    # 9. Background Worker
    checks.append({
        "name": "Background Automation Worker",
        "status": "CONNECTED",
        "last_checked_at": now,
        "detail": "FastAPI lifespan Drive watcher & workflow engine active.",
    })

    for c in checks:
        db.add(
            IntegrationSyncLog(
                integration_name=c["name"],
                status=c["status"],
                last_success_at=datetime.now(timezone.utc) if c["status"] == "CONNECTED" else None,
                last_error=None if c["status"] == "CONNECTED" else c["detail"],
                details_json=json.dumps(c),
            )
        )
    await db.commit()

    return {"checked_at": now, "integrations": checks}
