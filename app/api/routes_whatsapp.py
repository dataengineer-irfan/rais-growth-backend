from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_admin
from app.models.entities import WhatsAppMessage
from app.services.whatsapp_service import WHATSAPP_TEMPLATES, whatsapp_service

router = APIRouter(prefix="/whatsapp", tags=["WhatsApp Business Cloud API"])


class WhatsAppConnectPayload(BaseModel):
    phone_number_id: str = Field(..., min_length=4)
    access_token: str = Field(..., min_length=10)
    waba_id: Optional[str] = None
    verify_token: Optional[str] = None


class WhatsAppSendPayload(BaseModel):
    phone: str = Field(..., min_length=8)
    body: str = Field(..., min_length=1)
    lead_id: Optional[int] = None
    template_name: Optional[str] = None


@router.get("/webhook")
async def verify_whatsapp_webhook(
    hub_mode: Optional[str] = Query(default=None, alias="hub.mode"),
    hub_verify_token: Optional[str] = Query(default=None, alias="hub.verify_token"),
    hub_challenge: Optional[str] = Query(default=None, alias="hub.challenge"),
    db: AsyncSession = Depends(get_db),
):
    creds = await whatsapp_service.get_credentials(db)
    if hub_mode == "subscribe" and hub_verify_token == creds["verify_token"] and hub_challenge is not None:
        return Response(content=hub_challenge, media_type="text/plain")
    raise HTTPException(status_code=403, detail="Webhook verification failed")


@router.post("/webhook")
async def receive_whatsapp_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    raw_body = await request.body()
    sig = request.headers.get("X-Hub-Signature-256")
    if not whatsapp_service.verify_webhook_signature(raw_body, sig):
        raise HTTPException(status_code=403, detail="Invalid X-Hub-Signature-256 webhook signature")
    payload = await request.json()
    res = await whatsapp_service.process_inbound_webhook(db, payload)
    return {"status": "OK", **res}


class WhatsAppHandoverPayload(BaseModel):
    phone: str = Field(..., min_length=6)
    assigned_owner: str = "Depot Sales Lead"
    notes: Optional[str] = None


@router.post("/handover", dependencies=[Depends(require_admin)])
async def handover_whatsapp_thread(body: WhatsAppHandoverPayload, db: AsyncSession = Depends(get_db)):
    return await whatsapp_service.handover_to_human(
        db=db,
        phone=body.phone,
        owner_name=body.assigned_owner,
        notes=body.notes,
    )


@router.get("/status", dependencies=[Depends(require_admin)])
async def get_whatsapp_status(db: AsyncSession = Depends(get_db)):
    return await whatsapp_service.get_status(db)


@router.post("/connect", dependencies=[Depends(require_admin)])
async def connect_whatsapp(body: WhatsAppConnectPayload, db: AsyncSession = Depends(get_db)):
    try:
        return await whatsapp_service.save_credentials(
            db=db,
            phone_number_id=body.phone_number_id,
            access_token=body.access_token,
            waba_id=body.waba_id,
            verify_token=body.verify_token,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/templates", dependencies=[Depends(require_admin)])
async def list_whatsapp_templates():
    return WHATSAPP_TEMPLATES


@router.get("/messages", dependencies=[Depends(require_admin)])
async def list_whatsapp_messages(limit: int = 100, db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(select(WhatsAppMessage).order_by(desc(WhatsAppMessage.created_at)).limit(limit))
    ).scalars().all()
    return [
        {
            "id": m.id,
            "wa_message_id": m.wa_message_id,
            "lead_id": m.lead_id,
            "direction": m.direction,
            "phone": m.phone,
            "message_type": m.message_type,
            "body": m.body,
            "template_name": m.template_name,
            "status": m.status,
            "error_detail": m.error_detail,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in rows
    ]


@router.post("/send", dependencies=[Depends(require_admin)])
async def send_whatsapp_message(body: WhatsAppSendPayload, db: AsyncSession = Depends(get_db)):
    return await whatsapp_service.send_text_message(
        db=db,
        phone=body.phone,
        body=body.body,
        lead_id=body.lead_id,
        template_name=body.template_name,
    )
