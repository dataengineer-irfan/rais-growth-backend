import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.database import init_db, AsyncSessionLocal
from app.seed_data.seed import seed_initial_data

from app.api.routes_business_info import router as business_info_router
from app.api.routes_campaigns import router as campaigns_router
from app.api.routes_reviews import router as reviews_router
from app.api.routes_google import router as google_router
from app.api.routes_seo import router as seo_router
from app.api.routes_leads import router as leads_router
from app.api.routes_automation import router as automation_router
from app.api.routes_youtube import router as youtube_router, run_autopilot_cycle
from app.api.routes_meta import router as meta_router


async def _drive_autopilot_loop():
    """Hands-free watcher: every 3 minutes scans Drive for new videos and auto-publishes YT + IG + FB + First Comments."""
    while True:
        try:
            await asyncio.sleep(180)
            async with AsyncSessionLocal() as session:
                await run_autopilot_cycle(session)
        except asyncio.CancelledError:
            break
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize DB and Seed Data
    await init_db()
    async with AsyncSessionLocal() as session:
        await seed_initial_data(session)
    autopilot_task = asyncio.create_task(_drive_autopilot_loop())
    try:
        yield
    finally:
        # Shutdown: Cancel background watcher cleanly
        autopilot_task.cancel()
        try:
            await autopilot_task
        except asyncio.CancelledError:
            pass

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="AI-Powered Google Business Profile Automation Platform for RAIS Agencies, Rayachoty.",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

import os
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# API Routers
app.include_router(business_info_router, prefix=settings.API_V1_STR)
app.include_router(campaigns_router, prefix=settings.API_V1_STR)
app.include_router(reviews_router, prefix=settings.API_V1_STR)
app.include_router(google_router, prefix=settings.API_V1_STR)
app.include_router(seo_router, prefix=settings.API_V1_STR)
app.include_router(leads_router, prefix=settings.API_V1_STR)
app.include_router(automation_router, prefix=settings.API_V1_STR)
app.include_router(youtube_router, prefix=settings.API_V1_STR)
app.include_router(meta_router, prefix=settings.API_V1_STR)

@app.get("/api/health", tags=["Health"])
async def health_check():
    return {
        "status": "HEALTHY",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "mode": "DEVELOPMENT_MOCK_GBP" if settings.USE_MOCK_GBP else "PRODUCTION_LIVE_GBP",
        "verified_location": "Rayachoty, Annamayya District, AP"
    }

# Static Frontend SPA Serving (Render Production Client Access)
static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if os.path.exists(static_dir):
    assets_dir = os.path.join(static_dir, "assets")
    if os.path.exists(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/", tags=["Dashboard SPA"], include_in_schema=False)
    async def serve_dashboard_root():
        index_file = os.path.join(static_dir, "index.html")
        if os.path.exists(index_file):
            return FileResponse(index_file)
        return {
            "service": settings.PROJECT_NAME,
            "version": settings.VERSION,
            "status": "ONLINE"
        }

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_dashboard_spa(full_path: str):
        if full_path.startswith("api") or full_path.startswith("docs") or full_path.startswith("openapi.json"):
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Not Found")
        file_path = os.path.join(static_dir, full_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        index_file = os.path.join(static_dir, "index.html")
        if os.path.exists(index_file):
            return FileResponse(index_file)
else:
    @app.get("/", tags=["Root"])
    async def root():
        return {
            "service": settings.PROJECT_NAME,
            "version": settings.VERSION,
            "status": "ONLINE",
            "docs_url": "/docs",
            "health_check": "/api/health",
            "google_status": f"{settings.API_V1_STR}/google/status",
            "verified_location": "Rayachoty, Annamayya District, Andhra Pradesh"
        }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
