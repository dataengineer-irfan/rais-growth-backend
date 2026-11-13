import json
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import Column, Integer, String, Text, DateTime
from app.core.database import Base

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    action = Column(String(100), nullable=False, index=True)
    actor = Column(String(100), default="SYSTEM", index=True)
    resource_type = Column(String(50), nullable=False, index=True)
    resource_id = Column(String(100), nullable=True)
    details = Column(Text, nullable=True)
    ip_address = Column(String(50), nullable=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

async def log_audit(
    db: AsyncSession,
    action: str,
    resource_type: str,
    resource_id: str = None,
    actor: str = "SYSTEM",
    details: dict = None,
    ip_address: str = None
):
    """Immutable audit logging for compliance and tracking."""
    details_str = json.dumps(details) if details else None
    log_entry = AuditLog(
        action=action,
        actor=actor,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        details=details_str,
        ip_address=ip_address,
        timestamp=datetime.now(timezone.utc)
    )
    db.add(log_entry)
    await db.commit()
