from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.security import require_admin
from app.services.business_info_service import business_info_service
from app.schemas.schemas import (
    BusinessProfileRead, BusinessProfileUpdate,
    CatalogSKURead, CatalogSKUUpdate, CatalogSKUBase,
    ServiceAreaRead, ServiceAreaBase
)

router = APIRouter(prefix="/business-info", tags=["Business Information Management"])

@router.get("", response_model=BusinessProfileRead)
@router.get("/", response_model=BusinessProfileRead, include_in_schema=False)
@router.get("/profile", response_model=BusinessProfileRead)
async def get_profile(db: AsyncSession = Depends(get_db)):
    """Fetch current editable business profile."""
    return await business_info_service.get_or_create_profile(db)

@router.put("/profile", response_model=BusinessProfileRead, dependencies=[Depends(require_admin)])
async def update_profile(data: BusinessProfileUpdate, db: AsyncSession = Depends(get_db)):
    """Update business profile information (address, phone, categories, etc.) without touching code."""
    return await business_info_service.update_profile(db, data)

@router.get("/skus", response_model=List[CatalogSKURead])
async def list_skus(db: AsyncSession = Depends(get_db)):
    """List all approved catalog SKUs."""
    return await business_info_service.list_skus(db)

@router.post("/skus", response_model=CatalogSKURead, dependencies=[Depends(require_admin)])
async def add_sku(data: CatalogSKUBase, db: AsyncSession = Depends(get_db)):
    """Add a new product SKU to the catalog and emit new_product workflow event."""
    from app.services.automation_engine import automation_engine

    sku = await business_info_service.add_sku(db, data)
    await automation_engine.trigger_event(
        db=db,
        trigger_type="new_product",
        payload={"sku": sku.sku, "theme": f"New Catalog Product: {sku.name}"},
        idempotency_key=f"new-sku-{sku.sku}",
    )
    return sku

@router.put("/skus/{sku_id}", response_model=CatalogSKURead, dependencies=[Depends(require_admin)])
async def update_sku(sku_id: int, data: CatalogSKUUpdate, db: AsyncSession = Depends(get_db)):
    """Update stock status, pack size, or description of a catalog SKU."""
    from app.services.automation_engine import automation_engine

    try:
        sku = await business_info_service.update_sku(db, sku_id, data)
        if data.in_stock is True:
            await automation_engine.trigger_event(
                db=db,
                trigger_type="stock_arrival",
                payload={"sku": sku.sku, "theme": f"Fresh Stock Arrival: {sku.name}"},
            )
        return sku
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.get("/service-areas", response_model=List[ServiceAreaRead])
async def list_service_areas(db: AsyncSession = Depends(get_db)):
    """List commercial service areas."""
    return await business_info_service.list_service_areas(db)
