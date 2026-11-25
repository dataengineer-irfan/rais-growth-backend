import base64
import json
import re
from typing import Any, Dict, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import decrypt_token
from app.models.entities import YouTubeDriveSetting

DEPOT_PHONE = "9347453135"
DEPOT_ADDRESS = (
    "Beside Indel Money Bank, Sundupalli Road, Opp. Reddies Colony, "
    "Rayachoty – 516269, Annamayya District, Andhra Pradesh"
)
CORRIDORS = (
    "Rayachoty, Sundupalli, Galiveedu, Kadiri, Chinnamandem, "
    "Kalakada, Mahal, Madanapalle, Kadapa & Rajampet"
)
DEFAULT_HASHTAGS = (
    "#RAISAgencies #Rayachoty #AnnamayyaDistrict #FrozenFoodWholesale "
    "#CafeSupplies #FastFoodSupply #QSRKitchen #WholesaleRayachoty"
)


def build_default_first_comment(product_name: str, extra_tags: str = "") -> str:
    tag_line = f"{DEFAULT_HASHTAGS} {extra_tags}".strip()
    return (
        f"📍 Depot Hub: RAIS Agencies, {DEPOT_ADDRESS}\n"
        f"📲 Wholesale Stock & Same-Day Dispatch Inquiry ({product_name}): WhatsApp +91 {DEPOT_PHONE} -> https://wa.me/91{DEPOT_PHONE}\n"
        f"🚚 Daily Supply Routes: {CORRIDORS}\n\n"
        f"{tag_line}"
    )[:2000]


class VideoAIService:
    """
    Analyzes uploaded Drive videos using Gemini Video Vision (when GEMINI_API_KEY is configured)
    and builds viral hook titles, bilingual Telugu+English captions, hashtags, and pinned first comments.
    """

    GEMINI_ENDPOINT_TEMPLATE = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "{model}:generateContent"
    )
    GEMINI_MODELS = (
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-3.8-flash",
        "gemini-3.7-flash",
        "gemini-flash-latest",
        "gemini-3-flash-preview",
        "gemini-2.5-flash",
    )
    MAX_INLINE_BYTES = 19 * 1024 * 1024  # Safe under 20MB inline Gemini limit

    @classmethod
    async def resolve_gemini_key(cls, db: AsyncSession) -> Optional[str]:
        stmt = select(YouTubeDriveSetting).limit(1)
        stg = (await db.execute(stmt)).scalar_one_or_none()
        if stg and stg.encrypted_gemini_api_key:
            dec = decrypt_token(stg.encrypted_gemini_api_key)
            if dec:
                return dec.strip()
        if settings.GEMINI_API_KEY:
            return settings.GEMINI_API_KEY.strip()
        return None

    @classmethod
    def is_generic_filename(cls, file_name: str) -> bool:
        stem = (file_name or "").rsplit(".", 1)[0].strip().lower()
        cleaned = re.sub(
            r"\b(vid|img|mov|mp4|reel|video|whatsapp|clip|copy|final|export|screenrecording)\b",
            "",
            stem,
        )
        cleaned = re.sub(r"[\d_\-\.\s:]+", "", cleaned)
        return len(cleaned) < 3

    @classmethod
    def fallback_viral_copy(
        cls, file_name: str, drive_description: str = ""
    ) -> Dict[str, Any]:
        hint_raw = f"{file_name or ''} {drive_description or ''}".strip()
        lower = hint_raw.lower()

        if "fries" in lower or "amul" in lower or "hup" in lower:
            sku = "VEG-001"
            prod = "2.5 KG Jumbo French Fries (Amul & Hup Hup)"
            title = "Crispy 2.5 KG Jumbo French Fries Stock 🔥 Rayachoty Cafe Wholesale | RAIS Agencies"
            hook = "🔥 Cafe & Fast-Food Owners in Rayachoty! Crispy Golden French Fries Jumbo Packs Now Ready at Our Cold-Chain Hub!"
            extra_tags = "#FrenchFriesWholesale #AmulFrenchFries #HupHupFries #BurgerCafe"
        elif "mozzarella" in lower or "milky" in lower or "cheese" in lower:
            sku = "DAIRY-004"
            prod = "Milky Mist Diced Mozzarella Cheese (1kg & 2kg)"
            title = "🍕 Maximum Pizza Pull! Milky Mist Diced Mozzarella Wholesale | RAIS Rayachoty"
            hook = "🍕 Non-stop cheese pull for your Pizzeria & Cafe! Fresh -18°C Milky Mist Mozzarella stock ready for dispatch!"
            extra_tags = "#MozzarellaCheese #MilkyMist #PizzaSuppliesRayachoty"
        elif "momo" in lower or "triken" in lower:
            sku = "NONVEG-001"
            prod = "Triken Frozen Momos & Crispy Nuggets"
            title = "🥟 Hot-Selling Triken Momos Bulk Stock! High-Margin Cafe Supply | RAIS Agencies"
            hook = "🥟 Steam or fry in minutes — zero prep waste! Triken Chicken & Veg Momos bulk cartons ready in Rayachoty!"
            extra_tags = "#TrikenMomos #MomosWholesale #StreetFoodRayachoty"
        elif "butter" in lower or "ogr" in lower or "box" in lower or "pack" in lower:
            sku = "PACKAGING-001"
            prod = "Commercial Food Packaging, OGR Butter Paper & Pizza Boxes"
            title = "📦 Zero-Leak Takeaway Packaging & OGR Butter Paper | RAIS Agencies Rayachoty"
            hook = "📦 Upgrade your parcel game! Heavy-duty greaseproof wraps, burger boxes & pizza boxes at wholesale rates!"
            extra_tags = "#FoodPackaging #OGRButterPaper #PizzaBoxesWholesale"
        else:
            sku = "RAIS-B2B"
            prod = "Commercial Frozen Foods & QSR Supplies"
            title = "🔥 Rayachoty Cafe & QSR Wholesale Alert! Fresh Frozen Stock Ready | RAIS Agencies"
            hook = (
                "🔥 రాయచోటి కేఫ్స్, పిజ్జా సెంటర్లు & ఫాస్ట్ ఫుడ్ ఓనర్స్ కోసం హోల్‌సేల్ అప్‌డేట్!\n"
                "Fresh -18°C Frozen Fries, Mozzarella Cheese, Momos & Packaging now ready at RAIS Agencies!"
            )
            extra_tags = "#RayachotyCafes #B2BFoodSupply #FrozenFoodDepot"

        caption = (
            f"{hook}\n\n"
            f"🏪 Depot Hub: {DEPOT_ADDRESS}\n"
            f"📲 Wholesale Trade Orders (WhatsApp / Call): +91 {DEPOT_PHONE}\n"
            f"💬 Quick Order Link: https://wa.me/91{DEPOT_PHONE}?text=Hi+RAIS+Agencies,+send+wholesale+rates\n"
            f"🚚 Routes: {CORRIDORS}\n\n"
            f"{DEFAULT_HASHTAGS} {extra_tags}"
        )
        first_comment = build_default_first_comment(prod, extra_tags)
        tags = "RAISAgencies,Rayachoty,FrozenFoodWholesale,CafeSupplies,RestaurantSupplies,Shorts"
        return {
            "product_sku": sku,
            "product_name": prod,
            "video_title": title[:98],
            "description": caption,
            "first_comment": first_comment,
            "tags": tags,
            "ai_analyzed": False,
        }

    @classmethod
    def _sanitize_ai_result(cls, parsed: Dict[str, Any], file_name: str, drive_desc: str) -> Dict[str, Any]:
        fb = cls.fallback_viral_copy(file_name, drive_desc)
        title = str(parsed.get("video_title") or fb["video_title"]).strip()
        title = re.sub(r"\s+", " ", title)[:98]

        desc = str(parsed.get("description") or fb["description"]).strip()
        if DEPOT_PHONE not in desc:
            desc += f"\n\n📲 Wholesale Orders (WhatsApp): +91 {DEPOT_PHONE} -> https://wa.me/91{DEPOT_PHONE}"
        if "rayachoty" not in desc.lower():
            desc += f"\n📍 {DEPOT_ADDRESS}"
        if "#" not in desc:
            desc += f"\n\n{DEFAULT_HASHTAGS}"

        first_comment = str(parsed.get("first_comment") or "").strip()
        if not first_comment:
            first_comment = build_default_first_comment(str(parsed.get("product_name") or fb["product_name"]))
        elif DEPOT_PHONE not in first_comment:
            first_comment += f"\n📲 Order on WhatsApp: +91 {DEPOT_PHONE} | 📍 Rayachoty"

        return {
            "product_sku": str(parsed.get("product_sku") or fb["product_sku"])[:45],
            "product_name": str(parsed.get("product_name") or fb["product_name"])[:190],
            "video_title": title,
            "description": desc[:2150],
            "first_comment": first_comment[:1900],
            "tags": str(parsed.get("tags") or fb["tags"])[:480],
            "ai_analyzed": True,
        }

    @classmethod
    async def analyze_drive_video(
        cls,
        file_name: str,
        drive_description: str = "",
        video_bytes: Optional[bytes] = None,
        gemini_api_key: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> Dict[str, Any]:
        """
        Inspects real MP4 video bytes via Gemini 2.5 Flash Vision when an API key is available
        so numeric phone filenames still get rich product-specific viral hooks, bilingual Telugu+English
        captions, hashtags, and an automatic first comment.
        """
        if not gemini_api_key or not video_bytes or len(video_bytes) > cls.MAX_INLINE_BYTES:
            return cls.fallback_viral_copy(file_name, drive_description)

        prompt = (
            "Watch this promotional video uploaded for RAIS Agencies (Rayachoty, Annamayya District, Andhra Pradesh) "
            "and write high-converting social media metadata for YouTube Shorts, Instagram Reels, and Facebook Page.\n\n"
            "Verified business facts to always use cleanly:\n"
            f"- Business: RAIS Agencies\n"
            f"- Address: {DEPOT_ADDRESS}\n"
            f"- Verified WhatsApp Order Phone: {DEPOT_PHONE} (ALWAYS use {DEPOT_PHONE} even if any graphic shows a typo)\n"
            f"- Supply Corridors: {CORRIDORS}\n\n"
            "Identify the exact product(s), pack size, brand, and on-screen offer or Telugu/English voiceover from the video. "
            "Never include the raw numeric filename in the title.\n"
            "Return STRICT JSON with exactly these keys:\n"
            "{\n"
            '  "product_sku": "short code like VEG-001, DAIRY-004, NONVEG-001, PACKAGING-001, or RAIS-B2B",\n'
            '  "product_name": "exact product & brand seen/heard in the video",\n'
            '  "video_title": "viral scroll-stopping title under 95 characters with key hook/product",\n'
            '  "description": "viral hook opening + punchy Telugu & English commercial description matching the video + WhatsApp link https://wa.me/919347453135 + depot address + 8-12 targeted hashtags",\n'
            '  "first_comment": "pinned first comment with Rayachoty depot address pin, delivery routes, WhatsApp 9347453135 CTA, and local Rayachoty/Annamayya hashtags",\n'
            '  "tags": "comma,separated,youtube,tags"\n'
            "}"
        )

        body = {
            "contents": [
                {
                    "parts": [
                        {
                            "inline_data": {
                                "mime_type": "video/mp4",
                                "data": base64.b64encode(video_bytes).decode("ascii"),
                            }
                        },
                        {"text": prompt},
                    ]
                }
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.4,
            },
        }

        async def _call(http: httpx.AsyncClient) -> Dict[str, Any]:
            last_err = ""
            for model in cls.GEMINI_MODELS:
                url = cls.GEMINI_ENDPOINT_TEMPLATE.format(model=model)
                resp = await http.post(url, params={"key": gemini_api_key}, json=body)
                if resp.status_code == 200:
                    data = resp.json()
                    text = (
                        data.get("candidates", [{}])[0]
                        .get("content", {})
                        .get("parts", [{}])[0]
                        .get("text", "{}")
                    )
                    parsed = json.loads(text)
                    if isinstance(parsed, list) and parsed:
                        parsed = parsed[0]
                    return cls._sanitize_ai_result(
                        parsed if isinstance(parsed, dict) else {},
                        file_name,
                        drive_description,
                    )
                last_err = f"{model} ({resp.status_code}): {resp.text[:160]}"
                if resp.status_code not in (404, 429, 500, 502, 503, 504):
                    break
            raise ValueError(f"All Gemini Video Vision models unavailable: {last_err}")

        try:
            if client is not None:
                return await _call(client)
            async with httpx.AsyncClient(timeout=60.0) as local_http:
                return await _call(local_http)
        except Exception:
            return cls.fallback_viral_copy(file_name, drive_description)
