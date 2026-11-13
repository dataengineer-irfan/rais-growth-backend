import re
from typing import Dict, Any, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.entities import CatalogSKU, VerificationStatus
from app.core.config import settings

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

    async def generate_campaign_post(
        self,
        db: AsyncSession,
        theme: str,
        target_sku: Optional[str] = None,
        language_mode: str = "bilingual"
    ) -> Dict[str, Any]:
        """
        Generates compliant B2B promotional copy with Telugu & English text,
        then subjects it to deterministic validation.
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

        # Structured high-converting B2B templates
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
            "theme": theme
        }

        # Deterministic validation
        validation_report = await self.validate_post_content(db, candidate)
        candidate["validation_report"] = validation_report
        return candidate

ai_content_engine = AIContentEngine()
