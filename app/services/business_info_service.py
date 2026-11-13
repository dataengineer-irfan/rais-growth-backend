from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.models.entities import BusinessProfile, CatalogSKU, ServiceArea, VerificationStatus
from app.schemas.schemas import BusinessProfileUpdate, CatalogSKUUpdate, CatalogSKUBase, ServiceAreaBase
from app.core.audit import log_audit

class BusinessInfoService:
    """Editable Business Information, Catalog SKU, and Service Area Management."""

    async def get_or_create_profile(self, db: AsyncSession) -> BusinessProfile:
        stmt = select(BusinessProfile).limit(1)
        res = await db.execute(stmt)
        profile = res.scalar_one_or_none()
        if not profile:
            profile = BusinessProfile()
            db.add(profile)
            await db.commit()
            await db.refresh(profile)
        return profile

    async def update_profile(self, db: AsyncSession, update_data: BusinessProfileUpdate, actor: str = "Admin") -> BusinessProfile:
        profile = await self.get_or_create_profile(db)
        data_dict = update_data.model_dump(exclude_unset=True)
        for key, val in data_dict.items():
            setattr(profile, key, val)
        profile.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(profile)

        await log_audit(
            db=db,
            action="BUSINESS_PROFILE_UPDATED",
            resource_type="BUSINESS_PROFILE",
            actor=actor,
            details=data_dict
        )
        return profile

    async def list_skus(self, db: AsyncSession) -> List[CatalogSKU]:
        stmt = select(CatalogSKU).order_by(CatalogSKU.category, CatalogSKU.name)
        res = await db.execute(stmt)
        return res.scalars().all()

    async def update_sku(self, db: AsyncSession, sku_id: int, update_data: CatalogSKUUpdate, actor: str = "Admin") -> CatalogSKU:
        stmt = select(CatalogSKU).where(CatalogSKU.id == sku_id)
        res = await db.execute(stmt)
        item = res.scalar_one_or_none()
        if not item:
            raise ValueError(f"SKU with ID {sku_id} not found.")

        data_dict = update_data.model_dump(exclude_unset=True)
        for key, val in data_dict.items():
            setattr(item, key, val)
        await db.commit()
        await db.refresh(item)

        await log_audit(
            db=db,
            action="CATALOG_SKU_UPDATED",
            resource_type="CATALOG_SKU",
            resource_id=str(sku_id),
            actor=actor,
            details=data_dict
        )
        return item

    async def add_sku(self, db: AsyncSession, sku_data: CatalogSKUBase, actor: str = "Admin") -> CatalogSKU:
        new_sku = CatalogSKU(**sku_data.model_dump())
        db.add(new_sku)
        await db.commit()
        await db.refresh(new_sku)

        await log_audit(
            db=db,
            action="CATALOG_SKU_CREATED",
            resource_type="CATALOG_SKU",
            resource_id=new_sku.sku,
            actor=actor,
            details={"name": new_sku.name, "category": new_sku.category}
        )
        return new_sku

    async def list_service_areas(self, db: AsyncSession) -> List[ServiceArea]:
        stmt = select(ServiceArea).order_by(ServiceArea.is_primary.desc(), ServiceArea.area_name)
        res = await db.execute(stmt)
        return res.scalars().all()

business_info_service = BusinessInfoService()
