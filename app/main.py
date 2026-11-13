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

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize DB and Seed Data
    await init_db()
    async with AsyncSessionLocal() as session:
        await seed_initial_data(session)
    yield
    # Shutdown: Clean up any active connections
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

# API Routers
app.include_router(business_info_router, prefix=settings.API_V1_STR)
app.include_router(campaigns_router, prefix=settings.API_V1_STR)
app.include_router(reviews_router, prefix=settings.API_V1_STR)
app.include_router(google_router, prefix=settings.API_V1_STR)
app.include_router(seo_router, prefix=settings.API_V1_STR)
app.include_router(leads_router, prefix=settings.API_V1_STR)
app.include_router(automation_router, prefix=settings.API_V1_STR)

@app.get("/api/health", tags=["Health"])
async def health_check():
    return {
        "status": "HEALTHY",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "mode": "DEVELOPMENT_MOCK_GBP" if settings.USE_MOCK_GBP else "PRODUCTION_LIVE_GBP",
        "verified_location": "Rayachoty, Annamayya District, AP"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
