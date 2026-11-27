import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_admin
from app.models.entities import (
    AIGenerationLog,
    AnalyticsEvent,
    B2BLead,
    CatalogSKU,
    CustomerEnquiry,
    LeadStatus,
    Review,
    WorkflowExecution,
    WorkflowExecutionStatus,
    YouTubeQueueItem,
)
from app.services.video_ai_service import VideoAIService

router = APIRouter(
    prefix="/ai",
    tags=["RAIS AI Business Intelligence & Content Factory"],
    dependencies=[Depends(require_admin)],
)


class AIAskPayload(BaseModel):
    question: str = Field(..., min_length=2, max_length=500)


class ContentFactoryPayload(BaseModel):
    channel: str = Field(default="gbp")  # gbp, whatsapp, reel_script, youtube, meta
    theme: str = Field(..., min_length=2, max_length=200)
    target_sku: Optional[str] = None
    language: str = Field(default="bilingual")  # english, telugu, hindi, bilingual, trilingual
    variations: int = Field(default=1, ge=1, le=3)


@router.post("/ask")
async def ask_business_intelligence(body: AIAskPayload, db: AsyncSession = Depends(get_db)):
    """
    Queries real Neon PostgreSQL tables to answer operational B2B questions.
    Never invents database facts; cites exact source tables and record IDs.
    """
    q = body.question.lower()
    now = datetime.now(timezone.utc)
    sources: List[str] = []
    supporting_records: List[Dict[str, Any]] = []
    facts: List[str] = []

    if any(k in q for k in ("lead", "follow", "cafe", "interested", "inactive", "customer")):
        leads = (await db.execute(select(B2BLead).order_by(desc(B2BLead.created_at)))).scalars().all()
        sources.append("b2b_leads")
        due_followups = [
            l for l in leads
            if l.next_followup_at and l.next_followup_at <= now + timedelta(days=1)
        ]
        cafes = [l for l in leads if "cafe" in (l.business_type or "").lower() or "qsr" in (l.business_type or "").lower()]
        inactive = [
            l for l in leads
            if l.status == LeadStatus.CONVERTED and (not l.last_interaction_at or l.last_interaction_at < now - timedelta(days=14))
        ]
        facts.append(f"Total B2B leads in CRM: {len(leads)}.")
        facts.append(f"Follow-ups due within 24h: {len(due_followups)}.")
        facts.append(f"Cafe/QSR leads: {len(cafes)}.")
        if inactive:
            facts.append(f"Converted customers with >14 days inactivity: {len(inactive)}.")
        for l in (due_followups or cafes or leads)[:8]:
            supporting_records.append({
                "table": "b2b_leads",
                "id": l.id,
                "business_name": l.business_name,
                "status": l.status.value,
                "lead_score": l.lead_score,
                "location": l.location,
            })

    if any(k in q for k in ("enquir", "product", "order", "promote", "stock", "sku")):
        enqs = (await db.execute(select(CustomerEnquiry).order_by(desc(CustomerEnquiry.created_at)))).scalars().all()
        skus = (await db.execute(select(CatalogSKU))).scalars().all()
        sources.extend(["customer_enquiries", "catalog_skus"])
        in_stock_focus = [s for s in skus if s.in_stock and s.is_commercial_focus]
        facts.append(f"Total recorded customer enquiries: {len(enqs)}.")
        facts.append(f"Verified catalog SKUs: {len(skus)} ({len(in_stock_focus)} commercial focus in stock).")
        for e in enqs[:5]:
            supporting_records.append({
                "table": "customer_enquiries",
                "id": e.id,
                "customer_name": e.customer_name,
                "product_sku": e.product_sku,
                "status": e.status,
            })
        for s in in_stock_focus[:5]:
            supporting_records.append({
                "table": "catalog_skus",
                "id": s.id,
                "sku": s.sku,
                "name": s.name,
                "in_stock": s.in_stock,
            })

    if any(k in q for k in ("review", "rating", "reply")):
        revs = (await db.execute(select(Review).order_by(desc(Review.create_time)))).scalars().all()
        sources.append("reviews")
        unanswered = [r for r in revs if not r.has_replied]
        facts.append(f"Total reviews: {len(revs)}, Unanswered: {len(unanswered)}.")
        for r in unanswered[:6]:
            supporting_records.append({
                "table": "reviews",
                "id": r.id,
                "author": r.author_name,
                "rating": r.rating,
                "has_replied": r.has_replied,
            })

    if any(k in q for k in ("fail", "automation", "workflow", "today", "attention", "post", "perform")):
        execs = (await db.execute(select(WorkflowExecution).order_by(desc(WorkflowExecution.created_at)).limit(30))).scalars().all()
        vids = (await db.execute(select(YouTubeQueueItem).order_by(desc(YouTubeQueueItem.created_at)).limit(20))).scalars().all()
        sources.extend(["workflow_executions", "youtube_queue_items"])
        failed = [e for e in execs if e.status == WorkflowExecutionStatus.FAILED]
        awaiting = [e for e in execs if e.status == WorkflowExecutionStatus.AWAITING_APPROVAL]
        facts.append(f"Recent workflow runs: {len(execs)} (Failed: {len(failed)}, Awaiting Approval: {len(awaiting)}).")
        facts.append(f"Synced video queue items: {len(vids)} (Published YT: {sum(1 for v in vids if v.youtube_url)}, IG: {sum(1 for v in vids if v.ig_url)}).")
        for ex in (failed + awaiting)[:5]:
            supporting_records.append({
                "table": "workflow_executions",
                "id": ex.id,
                "execution_uid": ex.execution_uid,
                "status": ex.status.value,
                "error": ex.error_message,
            })

    if not facts:
        lead_cnt = (await db.execute(select(func.count(B2BLead.id)))).scalar() or 0
        rev_cnt = (await db.execute(select(func.count(Review.id)))).scalar() or 0
        ev_cnt = (await db.execute(select(func.count(AnalyticsEvent.id)))).scalar() or 0
        sources = ["b2b_leads", "reviews", "analytics_events"]
        facts = [
            f"B2B Leads in Neon: {lead_cnt}",
            f"Google Reviews in Neon: {rev_cnt}",
            f"Storefront Analytics Events in Neon: {ev_cnt}",
        ]

    answer = " ".join(facts)
    provider = "database_query_engine"
    ai_status = "MISSING_API_KEY"
    fallback_reason: Optional[str] = "GEMINI_API_KEY is not configured"

    gemini_key = await VideoAIService.resolve_gemini_key(db)
    if gemini_key:
        ai_status = "API_ERROR"
        fallback_reason = "No Gemini model returned a valid response"
        try:
            prompt = (
                f"User question: {body.question}\n"
                f"Verified database facts (DO NOT invent anything outside these facts):\n{json.dumps(facts)}\n"
                f"Supporting records:\n{json.dumps(supporting_records[:10])}\n"
                "Provide a concise, factual operational answer citing only the numbers and records above."
            )
            async with httpx.AsyncClient(timeout=15.0) as client:
                for model in VideoAIService.GEMINI_MODELS:
                    url = VideoAIService.GEMINI_ENDPOINT_TEMPLATE.format(model=model)
                    resp = await client.post(url, params={"key": gemini_key}, json={"contents": [{"parts": [{"text": prompt}]}]})
                    if resp.status_code == 200:
                        txt = resp.json().get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
                        if txt:
                            answer = txt
                            provider = f"gemini:{model}"
                            ai_status = "SUCCESS"
                            fallback_reason = None
                            break
                    elif resp.status_code in (401, 403):
                        ai_status = "AUTH_ERROR"
                        fallback_reason = f"Gemini authentication failed ({resp.status_code})"
                        break
                    elif resp.status_code == 429:
                        ai_status = "RATE_LIMITED"
                        fallback_reason = "Gemini rate limit exceeded (429)"
                    else:
                        fallback_reason = f"Gemini returned HTTP {resp.status_code}"
        except httpx.TimeoutException:
            ai_status = "TIMEOUT"
            fallback_reason = "Gemini API request timed out"
        except Exception as exc:
            ai_status = "API_ERROR"
            fallback_reason = str(exc)

    db.add(
        AIGenerationLog(
            task_type="business_intelligence",
            provider=provider,
            prompt_summary=body.question[:280],
            output_preview=answer[:400],
            fallback_used=(provider == "database_query_engine"),
        )
    )
    await db.commit()

    return {
        "question": body.question,
        "answer": answer,
        "provider": provider,
        "ai_status": ai_status,
        "fallback_reason": fallback_reason,
        "sources": sorted(set(sources)),
        "supporting_records": supporting_records,
    }


@router.post("/content-factory")
async def generate_multi_platform_content(body: ContentFactoryPayload, db: AsyncSession = Depends(get_db)):
    sku_obj = None
    if body.target_sku:
        sku_obj = (await db.execute(select(CatalogSKU).where(CatalogSKU.sku == body.target_sku))).scalar_one_or_none()

    prod_label = f"{sku_obj.brand} {sku_obj.name} ({sku_obj.pack_size})" if sku_obj else body.theme
    price_line = (
        f"Verified Trade Rate: ₹{sku_obj.selling_price}/{sku_obj.price_unit or sku_obj.pack_size}"
        if (sku_obj and sku_obj.selling_price is not None)
        else "Trade rates shared directly on WhatsApp 9347453135."
    )

    ai_status = "MISSING_API_KEY"
    fallback_reason: Optional[str] = "GEMINI_API_KEY is not configured"
    gemini_key = await VideoAIService.resolve_gemini_key(db)
    if gemini_key:
        ai_status = "API_ERROR"
        fallback_reason = "Gemini returned no structured variations"
        prompt = (
            f"Create {body.variations} B2B marketing variation(s) for RAIS Agencies, Beside Indel Money Bank, Sundupalli Road, Rayachoty.\n"
            f"Channel: {body.channel} | Theme: {body.theme} | Product: {prod_label} | Language: {body.language}\n"
            f"Verified Price Policy: {price_line}\n"
            "Rules: Never invent prices, discounts, stock, or fake claims. Only use phone 9347453135.\n"
            "Return STRICT JSON: {\"variations\": [{\"headline\": \"...\", \"english\": \"...\", \"telugu\": \"...\", \"hindi\": \"...\", \"hashtags\": \"...\"}]}"
        )
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                for model in VideoAIService.GEMINI_MODELS:
                    url = VideoAIService.GEMINI_ENDPOINT_TEMPLATE.format(model=model)
                    resp = await client.post(
                        url,
                        params={"key": gemini_key},
                        json={
                            "contents": [{"parts": [{"text": prompt}]}],
                            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.5},
                        },
                    )
                    if resp.status_code == 200:
                        raw = resp.json().get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "{}")
                        parsed = json.loads(raw)
                        if parsed.get("variations"):
                            db.add(AIGenerationLog(task_type=f"content_{body.channel}", provider="gemini", model_used=model, prompt_summary=body.theme, fallback_used=False))
                            await db.commit()
                            return {
                                "generation_engine": "gemini",
                                "ai_status": "SUCCESS",
                                "fallback_reason": None,
                                "model": model,
                                "variations": parsed["variations"],
                            }
                    elif resp.status_code in (401, 403):
                        ai_status = "AUTH_ERROR"
                        fallback_reason = f"Gemini authentication failed ({resp.status_code})"
                        break
                    elif resp.status_code == 429:
                        ai_status = "RATE_LIMITED"
                        fallback_reason = "Gemini rate limit exceeded (429)"
                    else:
                        fallback_reason = f"Gemini returned HTTP {resp.status_code}"
        except httpx.TimeoutException:
            ai_status = "TIMEOUT"
            fallback_reason = "Gemini API request timed out"
        except Exception as exc:
            ai_status = "API_ERROR"
            fallback_reason = str(exc)

    # Explicit honest template fallback
    variations = []
    for idx in range(body.variations):
        variations.append({
            "headline": f"{body.theme} — {prod_label} | RAIS Agencies Rayachoty (Var {idx + 1})",
            "english": (
                f"Commercial B2B supply of {prod_label} available at RAIS Agencies, Beside Indel Money Bank, "
                f"Sundupalli Road, Rayachoty. -18°C cold-chain integrity for cafes, bakeries & QSR kitchens. {price_line}"
            ),
            "telugu": (
                f"రాయచోటి RAIS Agencies నుండి {prod_label} -18°C కోల్డ్ చైన్ హోల్‌సేల్ సప్లై. ఆర్డర్ల కోసం 9347453135 కు కాల్ లేదా వాట్సాప్ చేయండి."
            ),
            "hindi": (
                f"RAIS Agencies रायचोटी से {prod_label} की -18°C कोल्ड-चेन होलसेल सप्लाई। ऑर्डर के लिए 9347453135 पर WhatsApp करें।"
            ),
            "hashtags": "#RAISAgencies #Rayachoty #FrozenFoodWholesale #CafeSupplies #AnnamayyaDistrict",
        })

    db.add(AIGenerationLog(task_type=f"content_{body.channel}", provider="template_engine", prompt_summary=body.theme, fallback_used=True))
    await db.commit()
    return {
        "generation_engine": "template_engine",
        "ai_status": ai_status,
        "fallback_reason": fallback_reason,
        "model": None,
        "variations": variations,
    }
