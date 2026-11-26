import json
import re
from typing import Dict, Any, List, Optional
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.entities import CatalogSKU, VerificationStatus
from app.core.config import settings
from app.services.video_ai_service import VideoAIService

class AIContentEngine:
    """AI-Powered Content Generation and Strict Deterministic Validation Engine."""

    # Prohibited claims patterns (violating Google policies or unverified RAIS assertions)
    PROHIBITED_CLAIM_PATTERNS = [
        (r'authorized\s+distributor\s+of\s+(itc|milky\s+mist|amul)', 'Unsupported "Authorized Distributor" claim without certificate. Use "Authorized Stockist" or "Wholesale Partner".'),
        (r'\b60\+\s+(food\s+outlets|restaurants|cafes|clients)\b', 'Unverified client count ("60+"). Prohibited until ledger-verified.'),
        (r'\b24\s*(\/|\s*x\s*)\s*7\s+(free\s+)?delivery\b', 'Unverified "24/7 Delivery" guarantee. Prohibited unless 24-hr staffing verified.'),
        (r'\b(guaranteed\s+first\s+page|rank\s+#?1\s+on\s+google\s+maps)\b', 'Prohibited Google ranking guarantee.')
    ]

    # Price leak patterns (e.g. ₹150, Rs. 160, 155/kg)
    PRICE_LEAK_PATTERN = r'(₹|rs\.?|inr)\s*\d+|(\d+\s*\/\s*kg)'

    async def validate_post_content(self, db: AsyncSession, post_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        DETERMINISTIC VALIDATION ENGINE:
        Verifies product SKU, blocks price leaks, validates phone, and flags prohibited claims.
        """
        errors: List[str] = []
        warnings: List[str] = []

        combined_text = f"{post_data.get('headline', '')} {post_data.get('content_english', '')} {post_data.get('content_telugu', '')}"

        # 1. Product Catalog SKU Check
        target_sku = post_data.get("target_product_sku")
        if target_sku:
            stmt = select(CatalogSKU).where(CatalogSKU.sku == target_sku)
            res = await db.execute(stmt)
            sku_obj = res.scalar_one_or_none()
            if not sku_obj:
                errors.append(f"Target SKU '{target_sku}' does not exist in the approved RAIS catalog.")
            elif not sku_obj.in_stock:
                warnings.append(f"Target SKU '{target_sku}' is currently marked out-of-stock.")

        # 2. Price Leak Detection
        if re.search(self.PRICE_LEAK_PATTERN, combined_text, re.IGNORECASE):
            errors.append("Specific purchase price detected in public copy. Public wholesale price leaks violate RAIS B2B policy. Route pricing inquiries to WhatsApp desk 9347453135.")

        # 3. Phone Number Integrity
        phone_matches = re.findall(r'\b\d{10}\b', combined_text)
        for ph in phone_matches:
            if ph != settings.VERIFIED_PHONE:
                errors.append(f"Unverified phone number '{ph}' detected. Only primary line '{settings.VERIFIED_PHONE}' is approved.")

        # 4. Prohibited Marketing Claims
        for pattern, reason in self.PROHIBITED_CLAIM_PATTERNS:
            if re.search(pattern, combined_text, re.IGNORECASE):
                errors.append(f"Prohibited Claim: {reason}")

        # 5. Length & Character Bounds
        if len(post_data.get("content_english", "")) > 1500:
            errors.append("English content exceeds Google Business Profile limit of 1500 characters.")

        is_valid = len(errors) == 0
        return {
            "is_valid": is_valid,
            "errors": errors,
            "warnings": warnings,
            "verification_status": VerificationStatus.VERIFIED if is_valid else VerificationStatus.UNVERIFIED_DRAFT
        }

    async def _generate_with_gemini(
        self,
        gemini_key: str,
        theme: str,
        sku_name: str,
        category: str,
        target_sku: Optional[str],
        language_mode: str,
    ) -> Optional[Dict[str, str]]:
        prompt = (
            f"Write a Google Business Profile B2B promotional post for RAIS Agencies, {settings.VERIFIED_ADDRESS}.\n"
            f"Theme: {theme}\n"
            f"Product/SKU: {sku_name} ({category}, code: {target_sku or 'GENERAL'})\n"
            f"Language mode: {language_mode}\n"
            "Strict compliance rules:\n"
            "- NEVER include currency prices, Rs., INR, ₹ amounts, or per-kg rates.\n"
            f"- Only reference WhatsApp/phone {settings.VERIFIED_PHONE} (never any other 10-digit number).\n"
            "- NEVER claim 'Authorized Distributor of ITC/Amul/Milky Mist', '24/7 delivery', '60+ outlets', or '#1 rank'.\n"
            "- Focus on -18°C cold-chain reliability, commercial carton stock for cafes/QSRs/bakeries in Rayachoty & Annamayya District.\n"
            "- Return STRICT JSON with keys: headline (<=90 chars), content_english (<=600 chars), "
            "content_telugu (natural Telugu script summary <=450 chars, or empty string if language_mode=='english')."
        )
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.5},
        }
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                for model in VideoAIService.GEMINI_MODELS:
                    url = VideoAIService.GEMINI_ENDPOINT_TEMPLATE.format(model=model)
                    resp = await client.post(url, params={"key": gemini_key}, json=body)
                    if resp.status_code == 200:
                        text = (
                            resp.json()
                            .get("candidates", [{}])[0]
                            .get("content", {})
                            .get("parts", [{}])[0]
                            .get("text", "{}")
                        )
                        parsed = json.loads(text)
                        if isinstance(parsed, list) and parsed:
                            parsed = parsed[0]
                        if isinstance(parsed, dict) and parsed.get("headline") and parsed.get("content_english"):
                            return {
                                "headline": str(parsed["headline"]).strip()[:120],
                                "content_english": str(parsed["content_english"]).strip()[:1400],
                                "content_telugu": str(parsed.get("content_telugu") or "").strip()[:1000],
                            }
                    if resp.status_code not in (404, 429, 500, 502, 503, 504):
                        break
        except Exception:
            return None
        return None

    async def generate_campaign_post(
        self,
        db: AsyncSession,
        theme: str,
        target_sku: Optional[str] = None,
        language_mode: str = "bilingual"
    ) -> Dict[str, Any]:
        """
        Generates compliant B2B promotional copy using Gemini AI when configured
        (falling back to deterministic templates if unconfigured), then runs strict validation.
        """
        # Lookup SKU if provided
        sku_name = "Commercial Frozen Foods & Food Packaging"
        category = "Wholesale QSR Supplies"
        if target_sku:
            stmt = select(CatalogSKU).where(CatalogSKU.sku == target_sku)
            res = await db.execute(stmt)
            sku_obj = res.scalar_one_or_none()
            if sku_obj:
                sku_name = f"{sku_obj.brand} {sku_obj.name}"
                category = sku_obj.category

        generation_engine = "template_fallback"
        gemini_key = await VideoAIService.resolve_gemini_key(db)
        ai_out = (
            await self._generate_with_gemini(
                gemini_key=gemini_key,
                theme=theme,
                sku_name=sku_name,
                category=category,
                target_sku=target_sku,
                language_mode=language_mode,
            )
            if gemini_key
            else None
        )

        if ai_out:
            generation_engine = "gemini"
            headline = ai_out["headline"]
            content_english = ai_out["content_english"]
            content_telugu = ai_out["content_telugu"]
        else:
            headline = f"Wholesale {sku_name} for Cafes & QSRs in Rayachoty"
            content_english = (
                f"Power your commercial kitchen with premium {sku_name}. "
                f"Stored at guaranteed -18°C cold-chain standards at our Rayachoty hub beside Indel Money Bank. "
                f"Reliable local availability, commercial carton packaging, and fast delivery for restaurants and bakeries. "
                f"Contact our B2B desk for authorized trade pricing."
            )
            content_telugu = (
                f"రాయచోటిలోని కేఫ్‌లు, రెస్టారెంట్లు మరియు బేకరీల కొరకు నాణ్యమైన {sku_name} టోకు ధరలకే లభించును. "
                f"ఇండెల్ మనీ బ్యాంక్ పక్కన, సుండుపల్లి రోడ్ వద్ద గల రైస్ ఏజెన్సీస్ వద్ద ఫ్రెష్ స్టాక్ అందుబాటులో ఉంది. "
                f"ఆర్డర్స్ మరియు ట్రేడ్ రేట్స్ కొరకు మా వాట్సాప్ డెస్క్ 9347453135 నంబర్‌ను సంప్రదించండి."
            )

        candidate = {
            "headline": headline,
            "content_english": content_english,
            "content_telugu": content_telugu if language_mode in ["telugu", "bilingual"] else None,
            "call_to_action": "CALL_NOW",
            "target_product_sku": target_sku,
            "theme": theme,
            "generation_engine": generation_engine,
        }

        # Deterministic validation
        validation_report = await self.validate_post_content(db, candidate)
        # If Gemini draft triggered a policy validation error, cleanly fall back to verified compliant template
        if generation_engine == "gemini" and not validation_report["is_valid"]:
            generation_engine = "template_fallback"
            candidate["headline"] = f"Wholesale {sku_name} for Cafes & QSRs in Rayachoty"
            candidate["content_english"] = (
                f"Power your commercial kitchen with premium {sku_name}. "
                f"Stored at guaranteed -18°C cold-chain standards at our Rayachoty hub beside Indel Money Bank. "
                f"Reliable local availability, commercial carton packaging, and fast delivery for restaurants and bakeries. "
                f"Contact our B2B desk for authorized trade pricing."
            )
            if language_mode in ["telugu", "bilingual"]:
                candidate["content_telugu"] = (
                    f"రాయచోటిలోని కేఫ్‌లు, రెస్టారెంట్లు మరియు బేకరీల కొరకు నాణ్యమైన {sku_name} టోకు ధరలకే లభించును. "
                    f"ఇండెల్ మనీ బ్యాంక్ పక్కన, సుండుపల్లి రోడ్ వద్ద గల రైస్ ఏజెన్సీస్ వద్ద ఫ్రెష్ స్టాక్ అందుబాటులో ఉంది. "
                    f"ఆర్డర్స్ మరియు ట్రేడ్ రేట్స్ కొరకు మా వాట్సాప్ డెస్క్ 9347453135 నంబర్‌ను సంప్రదించండి."
                )
            candidate["generation_engine"] = generation_engine
            validation_report = await self.validate_post_content(db, candidate)

        candidate["validation_report"] = validation_report
        return candidate

ai_content_engine = AIContentEngine()
