from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_admin
from app.models.entities import MediaAsset

router = APIRouter(
    prefix="/media",
    tags=["Media Asset Library"],
    dependencies=[Depends(require_admin)],
)

MAX_DATA_URL_CHARS = 4_500_000  # ~3.2MB image in base64


class MediaAssetCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    filename: str = Field(..., min_length=1, max_length=255)
    file_path: str = Field(..., min_length=1, max_length=MAX_DATA_URL_CHARS)
    category: str = Field(default="Cold Storage", max_length=100)
    caption: Optional[str] = Field(default=None, max_length=1000)


class MediaAssetOut(BaseModel):
    id: int
    title: str
    filename: str
    file_path: str
    category: str
    caption: Optional[str] = None
    is_verified_real_shop_photo: bool

    model_config = {"from_attributes": True}


@router.get("", response_model=List[MediaAssetOut])
async def list_media_assets(db: AsyncSession = Depends(get_db)):
    """Lists all persisted depot/product media assets stored in Neon Postgres."""
    res = await db.execute(select(MediaAsset).order_by(MediaAsset.id.desc()))
    return list(res.scalars().all())


@router.post("", response_model=MediaAssetOut)
async def create_media_asset(
    payload: MediaAssetCreate,
    db: AsyncSession = Depends(get_db),
):
    """Persists a depot or product photo (data URI or HTTPS URL) in Neon Postgres."""
    fp = payload.file_path.strip()
    if not (
        fp.startswith("https://")
        or fp.startswith("http://")
        or fp.startswith("data:image/")
    ):
        raise HTTPException(
            status_code=400,
            detail="Only HTTPS/HTTP image URLs or base64 image data URIs are supported.",
        )

    asset = MediaAsset(
        title=payload.title.strip(),
        filename=payload.filename.strip(),
        file_path=fp,
        category=payload.category.strip() or "Cold Storage",
        caption=(payload.caption or "").strip() or "Uploaded depot photo for Google Maps & social publishing.",
        is_verified_real_shop_photo=True,
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return asset


@router.delete("/{asset_id}")
async def delete_media_asset(asset_id: int, db: AsyncSession = Depends(get_db)):
    """Removes a persisted media asset from Neon Postgres."""
    asset = (
        await db.execute(select(MediaAsset).where(MediaAsset.id == asset_id))
    ).scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Media asset not found")
    await db.delete(asset)
    await db.commit()
    return {"status": "DELETED", "id": asset_id}
