from typing import List, Dict, Any
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.audit import AuditLog
from app.models.entities import AutomationSetting
from app.schemas.schemas import AutomationSettingRead, AutomationSettingUpdate
from app.services.scheduler_service import scheduler_service

router = APIRouter(prefix="/automation", tags=["Automation Control Center"])

@router.get("/settings", response_model=AutomationSettingRead)
async def get_settings(db: AsyncSession = Depends(get_db)):
    """Fetch automation control settings."""
    stmt = select(AutomationSetting).limit(1)
    res = await db.execute(stmt)
    setting = res.scalar_one_or_none()
    if not setting:
        setting = AutomationSetting()
        db.add(setting)
        await db.commit()
        await db.refresh(setting)
    return setting

@router.put("/settings", response_model=AutomationSettingRead)
async def update_settings(data: AutomationSettingUpdate, db: AsyncSession = Depends(get_db)):
    """Update publishing schedules and automation constraints."""
    stmt = select(AutomationSetting).limit(1)
    res = await db.execute(stmt)
    setting = res.scalar_one_or_none()
    if not setting:
        setting = AutomationSetting()
        db.add(setting)

    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(setting, k, v)
    await db.commit()
    await db.refresh(setting)
    return setting

@router.post("/kill-switch")
async def toggle_kill_switch(active: bool, db: AsyncSession = Depends(get_db)):
    """EMERGENCY PAUSE: Immediately halts all automated publishing."""
    result = await scheduler_service.set_kill_switch(db, active)
    return {"emergency_kill_switch": result, "status": "ACTIVE_HALT" if result else "NORMAL"}

@router.get("/audit-logs")
async def get_audit_logs(limit: int = 50, db: AsyncSession = Depends(get_db)):
    """View immutable audit trail."""
    stmt = select(AuditLog).order_by(AuditLog.timestamp.desc()).limit(limit)
    res = await db.execute(stmt)
    logs = res.scalars().all()
    return [
        {
            "id": l.id,
            "action": l.action,
            "actor": l.actor,
            "resource_type": l.resource_type,
            "resource_id": l.resource_id,
            "details": l.details,
            "timestamp": l.timestamp.isoformat()
        }
        for l in logs
    ]
