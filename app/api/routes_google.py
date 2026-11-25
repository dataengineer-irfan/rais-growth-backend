import urllib.parse
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.services.gbp_service import gbp_service
from app.schemas.schemas import GoogleAuthorizeResponse, GoogleStatusResponse

router = APIRouter(prefix="/google", tags=["Google Business Profile API"])

@router.get("/authorize", response_model=GoogleAuthorizeResponse)
async def get_authorization_url(
    include_youtube: bool = Query(False, description="Include Google Drive and YouTube upload OAuth scopes"),
    db: AsyncSession = Depends(get_db)
):
    """
    Generates official Google OAuth 2.0 authorization URL with cryptographically secure state.
    Scopes cover Google Business Profile management, plus optional Google Drive & YouTube upload.
    """
    try:
        return await gbp_service.generate_authorization_url(db=db, include_youtube=include_youtube)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/callback")
@router.get("/oauth2callback", include_in_schema=False)
async def oauth_callback(
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    error_description: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """
    OAuth 2.0 redirect callback endpoint.
    Validates CSRF state, exchanges authorization code for tokens, and securely persists credentials.
    Guaranteed zero-500 catch-all to redirect back to cloud dashboard under all conditions.
    """
    try:
        frontend_url = getattr(settings, "FRONTEND_URL", "https://dataengineer-irfan.github.io/RAIS-AGENCIES").rstrip("/")
        # Hard safety guard: unconditionally eliminate any localhost or 127.0.0.1 redirect
        if not frontend_url or "localhost" in frontend_url or "127.0.0.1" in frontend_url:
            frontend_url = "https://dataengineer-irfan.github.io/RAIS-AGENCIES"
        
        # Build cloud target redirect: if pointing to GitHub Pages, append hash to return straight to admin dashboard
        success_target = f"{frontend_url}/?google_auth=success#/admin" if "github.io" in frontend_url else f"{frontend_url}/?google_auth=success"
        def error_target(msg: str) -> str:
            encoded_err = urllib.parse.quote(str(msg))
            return f"{frontend_url}/?google_auth=error&error_description={encoded_err}#/admin" if "github.io" in frontend_url else f"{frontend_url}/?google_auth=error&error_description={encoded_err}"
        
        # 1. Handle Google-side authorization errors (e.g., user clicked cancel)
        if error:
            err_msg = error_description or error or "Google authorization was cancelled or denied."
            return RedirectResponse(
                url=error_target(err_msg),
                status_code=302
            )

        # 2. Validate mandatory parameters
        if not code or not state:
            return RedirectResponse(
                url=error_target("Missing required code or state parameter"),
                status_code=302
            )

        # 3. Process callback: validate state, exchange code, fetch account details, encrypt & persist
        await gbp_service.process_oauth_callback(db=db, code=code, state=state)
        return RedirectResponse(
            url=success_target,
            status_code=302
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        safe_msg = urllib.parse.quote(str(e))
        fallback_url = f"https://dataengineer-irfan.github.io/RAIS-AGENCIES/?google_auth=error&error_description={safe_msg}#/admin"
        return RedirectResponse(
            url=fallback_url,
            status_code=302
        )

@router.get("/status", response_model=GoogleStatusResponse)
async def get_connection_status(db: AsyncSession = Depends(get_db)):
    """Check Google Business Profile API connection health and authorized location."""
    return await gbp_service.get_connection_status(db=db)

@router.get("/locations")
async def list_locations(db: AsyncSession = Depends(get_db)):
    """Discover locations under authorized Google account."""
    return await gbp_service.list_locations(db=db)

@router.get("/performance")
async def get_performance(
    force_state: Optional[str] = Query(
        None,
        description="Optional state simulator for UI verification: CONNECTED_BUT_NO_DATA, LIVE_DATA_AVAILABLE, API_ERROR"
    ),
    db: AsyncSession = Depends(get_db)
):
    """Retrieve Google Business Profile performance metrics strictly enforcing the 4-state authenticity model."""
    return await gbp_service.get_performance_metrics(db=db, force_state=force_state)
