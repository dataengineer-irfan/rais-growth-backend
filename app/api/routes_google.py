import urllib.parse
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.gbp_service import gbp_service
from app.schemas.schemas import GoogleAuthorizeResponse, GoogleStatusResponse

router = APIRouter(prefix="/google", tags=["Google Business Profile API"])

@router.get("/authorize", response_model=GoogleAuthorizeResponse)
async def get_authorization_url(db: AsyncSession = Depends(get_db)):
    """
    Generates official Google OAuth 2.0 authorization URL with cryptographically secure state.
    Scopes restricted strictly to verified business profile operations.
    """
    try:
        return await gbp_service.generate_authorization_url(db=db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/callback")
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
    """
    # 1. Handle Google-side authorization errors (e.g., user clicked cancel)
    if error:
        err_msg = error_description or error or "Google authorization was cancelled or denied."
        return RedirectResponse(
            url=f"http://localhost:5173/?google_auth=error&error_description={urllib.parse.quote(err_msg)}",
            status_code=302
        )

    # 2. Validate mandatory parameters
    if not code or not state:
        return RedirectResponse(
            url="http://localhost:5173/?google_auth=error&error_description=Missing+required+code+or+state+parameter",
            status_code=302
        )

    # 3. Process callback: validate state, exchange code, fetch account details, encrypt & persist
    try:
        await gbp_service.process_oauth_callback(db=db, code=code, state=state)
        return RedirectResponse(
            url="http://localhost:5173/?google_auth=success",
            status_code=302
        )
    except ValueError as e:
        return RedirectResponse(
            url=f"http://localhost:5173/?google_auth=error&error_description={urllib.parse.quote(str(e))}",
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
    )
):
    """Retrieve Google Business Profile performance metrics strictly enforcing the 4-state authenticity model."""
    return await gbp_service.get_performance_metrics(force_state=force_state)
