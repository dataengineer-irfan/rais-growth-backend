import hashlib
import hmac
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import decrypt_token, encrypt_token
from app.models.entities import (
    B2BLead,
    CatalogSKU,
    CustomerEnquiry,
    CustomerInteraction,
    WhatsAppConfig,
    WhatsAppMessage,
)


WHATSAPP_TEMPLATES = [
    {
        "name": "rais_wholesale_intro_en",
        "language": "en",
        "category": "UTILITY",
        "body": (
            "Namaste {{1}}, RAIS Agencies (Beside Indel Money Bank, Sundupalli Road, Rayachoty) supplies "
            "frozen snacks, Milky Mist mozzarella, French fries, Triken momos & 3-ply pizza boxes at -18°C cold-chain. "
            "Reply with your kitchen requirement or call 9347453135."
        ),
    },
    {
        "name": "rais_wholesale_intro_te",
        "language": "te",
        "category": "UTILITY",
        "body": (
            "నమస్తే {{1}}, రాయచోటి RAIS Agencies నుండి -18°C కోల్డ్ చైన్ ఫ్రోజెన్ స్నాక్స్, Milky Mist మోజారెల్లా, "
            "ఫ్రెంచ్ ఫ్రైస్ మరియు ప్యాకేజింగ్ సప్లై అందుబాటులో ఉంది. ఆర్డర్ వివరాలకు 9347453135 కు రిప్లై ఇవ్వండి."
        ),
    },
    {
        "name": "rais_wholesale_intro_hi",
        "language": "hi",
        "category": "UTILITY",
        "body": (
            "नमस्ते {{1}}, RAIS Agencies (Sundupalli Road, Rayachoty) से -18°C कोल्ड-चेन फ्रोजन स्नैक्स, "
            "Milky Mist मोज़रेला, फ्रेंच फ्राइज़ और पैकेजिंग होलसेल सप्लाई उपलब्ध है। अधिक जानकारी के लिए 9347453135 पर संपर्क करें।"
        ),
    },
]


def _normalize_phone(phone: str) -> str:
    digits = "".join(c for c in (phone or "") if c.isdigit())
    if len(digits) == 10:
        return "91" + digits
    return digits


class WhatsAppService:
    GRAPH_BASE = "https://graph.facebook.com/v21.0"

    async def get_credentials(self, db: AsyncSession) -> Dict[str, Any]:
        cfg = (await db.execute(select(WhatsAppConfig).order_by(WhatsAppConfig.id.desc()).limit(1))).scalar_one_or_none()
        token = decrypt_token(cfg.encrypted_access_token) if cfg and cfg.encrypted_access_token else settings.WHATSAPP_ACCESS_TOKEN
        phone_id = (cfg.phone_number_id if cfg and cfg.phone_number_id else settings.WHATSAPP_PHONE_NUMBER_ID) or ""
        waba_id = (cfg.waba_id if cfg and cfg.waba_id else settings.WHATSAPP_WABA_ID) or ""
        verify_token = (cfg.verify_token if cfg and cfg.verify_token else settings.WHATSAPP_VERIFY_TOKEN) or "rais-wa-verify-2026"
        return {
            "connected": bool(token and phone_id),
            "phone_number_id": phone_id,
            "waba_id": waba_id,
            "access_token": token,
            "verify_token": verify_token,
            "last_verified_at": cfg.last_verified_at.isoformat() if cfg and cfg.last_verified_at else None,
        }

    async def save_credentials(
        self,
        db: AsyncSession,
        phone_number_id: str,
        access_token: str,
        waba_id: Optional[str] = None,
        verify_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        # Verify token against Graph API
        verified = False
        error_msg = None
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{self.GRAPH_BASE}/{phone_number_id}",
                    params={"fields": "display_phone_number,verified_name"},
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if resp.status_code == 200:
                    verified = True
                else:
                    error_msg = f"Meta Graph API rejected credentials ({resp.status_code}): {resp.text[:250]}"
        except Exception as exc:
            error_msg = f"Failed to reach Meta Graph API: {exc}"

        if not verified:
            raise ValueError(error_msg or "WhatsApp Cloud API verification failed")

        cfg = (await db.execute(select(WhatsAppConfig).order_by(WhatsAppConfig.id.desc()).limit(1))).scalar_one_or_none()
        if not cfg:
            cfg = WhatsAppConfig()
            db.add(cfg)
        cfg.phone_number_id = phone_number_id.strip()
        cfg.waba_id = (waba_id or "").strip() or None
        cfg.encrypted_access_token = encrypt_token(access_token.strip())
        if verify_token:
            cfg.verify_token = verify_token.strip()
        cfg.is_connected = True
        cfg.last_verified_at = datetime.now(timezone.utc)
        await db.commit()
        return await self.get_status(db)

    async def get_status(self, db: AsyncSession) -> Dict[str, Any]:
        creds = await self.get_credentials(db)
        return {
            "connected": creds["connected"],
            "status": "CONNECTED" if creds["connected"] else "NOT_CONNECTED",
            "phone_number_id": creds["phone_number_id"] or None,
            "waba_id": creds["waba_id"] or None,
            "verify_token": creds["verify_token"],
            "last_verified_at": creds["last_verified_at"],
            "message": (
                "WhatsApp Business Cloud API connected."
                if creds["connected"]
                else "WhatsApp Business Cloud API not configured. Provide Phone Number ID and Meta Cloud API Token."
            ),
        }

    async def send_text_message(
        self,
        db: AsyncSession,
        phone: str,
        body: str,
        lead_id: Optional[int] = None,
        template_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        norm_phone = _normalize_phone(phone)
        if not norm_phone:
            return {"sent": False, "status": "INVALID_PHONE", "error": "Valid phone number required."}

        # Respect opt-out
        lead = None
        if lead_id:
            lead = (await db.execute(select(B2BLead).where(B2BLead.id == lead_id))).scalar_one_or_none()
        if not lead:
            lead = (
                await db.execute(select(B2BLead).where(B2BLead.phone.contains(norm_phone[-10:])))
            ).scalar_one_or_none()
        if lead and lead.opted_out_whatsapp:
            return {"sent": False, "status": "OPTED_OUT", "error": "Contact has opted out of WhatsApp messages."}

        creds = await self.get_credentials(db)
        msg_rec = WhatsAppMessage(
            lead_id=lead.id if lead else lead_id,
            direction="OUTBOUND",
            phone=norm_phone,
            message_type="template" if template_name else "text",
            body=body,
            template_name=template_name,
            status="QUEUED",
        )
        db.add(msg_rec)
        await db.commit()
        await db.refresh(msg_rec)

        if not creds["connected"]:
            msg_rec.status = "FAILED"
            msg_rec.error_detail = "WhatsApp Business Cloud API not configured (missing token or phone_number_id)."
            await db.commit()
            return {
                "sent": False,
                "status": "NOT_CONNECTED",
                "message_id": msg_rec.id,
                "error": msg_rec.error_detail,
            }

        payload: Dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": norm_phone,
        }
        if template_name:
            tpl_lang = "en"
            for tpl in WHATSAPP_TEMPLATES:
                if tpl["name"] == template_name:
                    tpl_lang = tpl["language"]
                    break
            payload["type"] = "template"
            payload["template"] = {"name": template_name, "language": {"code": tpl_lang}}
        else:
            payload["type"] = "text"
            payload["text"] = {"body": body}

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    f"{self.GRAPH_BASE}/{creds['phone_number_id']}/messages",
                    headers={
                        "Authorization": f"Bearer {creds['access_token']}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            if resp.status_code in (200, 201):
                data = resp.json()
                wa_id = (data.get("messages") or [{}])[0].get("id")
                msg_rec.wa_message_id = wa_id
                msg_rec.status = "SENT"
                if lead:
                    lead.last_interaction_at = datetime.now(timezone.utc)
                    db.add(
                        CustomerInteraction(
                            lead_id=lead.id,
                            channel="WHATSAPP",
                            direction="OUTBOUND",
                            summary=body[:300],
                            created_by="whatsapp_cloud_api",
                        )
                    )
                await db.commit()
                return {"sent": True, "status": "SENT", "wa_message_id": wa_id, "message_id": msg_rec.id}

            msg_rec.status = "FAILED"
            msg_rec.error_detail = f"Graph API {resp.status_code}: {resp.text[:300]}"
            await db.commit()
            return {"sent": False, "status": "FAILED", "message_id": msg_rec.id, "error": msg_rec.error_detail}
        except Exception as exc:
            msg_rec.status = "FAILED"
            msg_rec.error_detail = str(exc)
            await db.commit()
            return {"sent": False, "status": "FAILED", "message_id": msg_rec.id, "error": str(exc)}

    def verify_webhook_signature(self, raw_body: bytes, signature_header: Optional[str]) -> bool:
        """Verifies Meta X-Hub-Signature-256 HMAC when META_APP_SECRET is configured."""
        secret = (settings.META_APP_SECRET or "").strip()
        if not secret:
            return True
        if not signature_header or not signature_header.startswith("sha256="):
            return False
        expected = "sha256=" + hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature_header.strip())

    async def handover_to_human(
        self,
        db: AsyncSession,
        phone: str,
        owner_name: str = "Depot Sales Lead",
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        norm = _normalize_phone(phone)
        lead = (
            await db.execute(select(B2BLead).where(B2BLead.phone.contains(norm[-10:])))
        ).scalar_one_or_none()
        if lead:
            lead.assigned_owner = owner_name
            db.add(
                CustomerInteraction(
                    lead_id=lead.id,
                    channel="WHATSAPP",
                    direction="INTERNAL",
                    summary=f"Human handover assigned to {owner_name}. {notes or ''}".strip(),
                    created_by=owner_name,
                )
            )
        enqs = (
            await db.execute(select(CustomerEnquiry).where(CustomerEnquiry.phone.contains(norm[-10:])))
        ).scalars().all()
        for e in enqs:
            if e.status in ("NEW", "QUOTED"):
                e.status = "HUMAN_HANDOVER"
                e.assigned_owner = owner_name
        await db.commit()
        return {"status": "HANDED_OVER", "assigned_owner": owner_name, "lead_id": lead.id if lead else None}

    async def process_inbound_webhook(self, db: AsyncSession, payload: Dict[str, Any]) -> Dict[str, Any]:
        processed = 0
        for entry in payload.get("entry") or []:
            for change in entry.get("changes") or []:
                value = change.get("value") or {}
                contacts = {c.get("wa_id"): (c.get("profile") or {}).get("name") for c in (value.get("contacts") or [])}
                for m in value.get("messages") or []:
                    wa_id = m.get("id")
                    from_phone = _normalize_phone(m.get("from") or "")
                    text_body = ((m.get("text") or {}).get("body") or "").strip()
                    if not from_phone or not text_body:
                        continue
                    if wa_id:
                        dup = (
                            await db.execute(select(WhatsAppMessage).where(WhatsAppMessage.wa_message_id == wa_id))
                        ).scalar_one_or_none()
                        if dup:
                            continue

                    lead = (
                        await db.execute(select(B2BLead).where(B2BLead.phone.contains(from_phone[-10:])))
                    ).scalar_one_or_none()
                    if not lead:
                        lead = B2BLead(
                            business_name=contacts.get(from_phone) or f"WhatsApp Lead {from_phone[-4:]}",
                            contact_person=contacts.get(from_phone),
                            phone=from_phone,
                            lead_source="WhatsApp Cloud API",
                        )
                        db.add(lead)
                        await db.commit()
                        await db.refresh(lead)

                    if text_body.upper() in ("STOP", "UNSUBSCRIBE", "OPT OUT"):
                        lead.opted_out_whatsapp = True

                    lead.last_interaction_at = datetime.now(timezone.utc)
                    db.add(
                        WhatsAppMessage(
                            wa_message_id=wa_id,
                            lead_id=lead.id,
                            direction="INBOUND",
                            phone=from_phone,
                            message_type=m.get("type") or "text",
                            body=text_body,
                            status="RECEIVED",
                        )
                    )
                    db.add(
                        CustomerInteraction(
                            lead_id=lead.id,
                            channel="WHATSAPP",
                            direction="INBOUND",
                            summary=text_body[:300],
                            created_by=contacts.get(from_phone) or from_phone,
                        )
                    )

                    # Match SKU if mentioned
                    matched_sku = None
                    skus = (await db.execute(select(CatalogSKU))).scalars().all()
                    lower_txt = text_body.lower()
                    for s in skus:
                        if s.sku.lower() in lower_txt or any(w in lower_txt for w in s.name.lower().split() if len(w) > 4):
                            matched_sku = s
                            break

                    enq = CustomerEnquiry(
                        lead_id=lead.id,
                        channel="WHATSAPP",
                        customer_name=lead.business_name,
                        phone=from_phone,
                        product_sku=matched_sku.sku if matched_sku else None,
                        product_name=matched_sku.name if matched_sku else None,
                        notes=text_body,
                        status="NEW",
                    )
                    db.add(enq)
                    await db.commit()
                    await db.refresh(enq)

                    from app.services.automation_engine import automation_engine

                    await automation_engine.trigger_event(
                        db=db,
                        trigger_type="new_enquiry",
                        payload={
                            "enquiry_id": enq.id,
                            "lead_id": lead.id,
                            "customer_name": lead.business_name,
                            "phone": from_phone,
                            "product_name": enq.product_name or "RAIS Wholesale Catalog",
                        },
                        idempotency_key=f"wa-{wa_id or enq.id}",
                    )
                    processed += 1

                for st in value.get("statuses") or []:
                    wa_id = st.get("id")
                    new_st = (st.get("status") or "").upper()
                    if wa_id and new_st:
                        rec = (
                            await db.execute(select(WhatsAppMessage).where(WhatsAppMessage.wa_message_id == wa_id))
                        ).scalar_one_or_none()
                        if rec:
                            rec.status = new_st
                            await db.commit()
        return {"processed": processed}


whatsapp_service = WhatsAppService()
