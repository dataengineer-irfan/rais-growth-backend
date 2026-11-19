from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.entities import Review, ReviewReplyDraft, SentimentType, ReviewOrigin, ReplyStatus
from app.core.audit import log_audit
from app.services.gbp_service import gbp_service

class ReviewService:
    """Customer Review Automation with Mandatory Explicit Human Approval Gate."""

    def classify_sentiment(self, rating: int, comment: Optional[str]) -> Dict[str, Any]:
        """Classifies sentiment and detects operational complaints."""
        is_complaint = False
        text = (comment or "").lower()

        complaint_keywords = ["bad", "delay", "thawed", "spoiled", "damage", "late", "melt", "leak", "worst", "shortage"]
        if any(w in text for w in complaint_keywords) or rating <= 2:
            is_complaint = True
            sentiment = SentimentType.NEGATIVE
        elif rating >= 4:
            sentiment = SentimentType.POSITIVE
        else:
            sentiment = SentimentType.NEUTRAL

        return {"sentiment": sentiment, "is_complaint": is_complaint}

    async def sync_reviews_from_gbp(self, db: AsyncSession, location_id: Optional[str] = None) -> int:
        """Fetches reviews from GBP and generates pending response drafts."""
        status = await gbp_service.get_connection_status(db=db)
        if not status.get("connected"):
            # Never fabricate reviews when unconnected
            return 0

        raw_reviews = await gbp_service.list_reviews(location_id=location_id, db=db)
        imported_count = 0

        rating_map = {
            "ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5,
            "1": 1, "2": 2, "3": 3, "4": 4, "5": 5
        }

        for r in raw_reviews:
            # Handle both Google camelCase (reviewId) and snake_case (review_id)
            r_id = r.get("reviewId") or r.get("review_id") or r.get("name")
            if not r_id:
                continue

            stmt = select(Review).where(Review.google_review_id == r_id)
            res = await db.execute(stmt)
            existing = res.scalar_one_or_none()

            # Map starRating enum string ("FIVE") or int
            raw_rating = r.get("starRating") or r.get("star_rating") or 5
            if isinstance(raw_rating, str):
                rating_val = rating_map.get(raw_rating.upper(), 5)
            elif isinstance(raw_rating, (int, float)):
                rating_val = int(raw_rating)
            else:
                rating_val = 5

            reviewer_obj = r.get("reviewer") if isinstance(r.get("reviewer"), dict) else {}
            author_name = (
                reviewer_obj.get("displayName") or
                reviewer_obj.get("display_name") or
                r.get("author_name") or
                "Valued Customer"
            )
            author_photo = reviewer_obj.get("profilePhotoUrl") or reviewer_obj.get("profile_photo_url") or r.get("author_photo_url")
            comment_text = r.get("comment")

            # Parse create time
            raw_time = r.get("createTime") or r.get("create_time")
            create_dt = datetime.now(timezone.utc)
            if raw_time:
                try:
                    create_dt = datetime.fromisoformat(str(raw_time).replace("Z", "+00:00"))
                except Exception:
                    pass

            has_reply = bool(r.get("reviewReply") or r.get("review_reply"))

            if not existing:
                analysis = self.classify_sentiment(rating_val, comment_text)
                new_rev = Review(
                    google_review_id=r_id,
                    author_name=author_name,
                    author_photo_url=author_photo,
                    rating=rating_val,
                    comment=comment_text,
                    create_time=create_dt,
                    sentiment=analysis["sentiment"],
                    is_complaint=analysis["is_complaint"],
                    has_replied=has_reply,
                    origin=ReviewOrigin.GOOGLE_AUTHENTIC
                )
                db.add(new_rev)
                await db.flush()

                # Generate bilingual response draft (PENDING APPROVAL)
                if not new_rev.has_replied:
                    draft = self.generate_response_draft(new_rev)
                    draft_obj = ReviewReplyDraft(
                        review_id=new_rev.id,
                        reply_english=draft["english"],
                        reply_telugu=draft["telugu"],
                        is_approved=False,
                        status=ReplyStatus.PENDING_APPROVAL.value
                    )
                    db.add(draft_obj)

                imported_count += 1
            else:
                if has_reply and not existing.has_replied:
                    existing.has_replied = True

        await db.commit()
        return imported_count

    def generate_response_draft(self, review: Review) -> Dict[str, str]:
        """
        Algorithmic B2B Keyword & Entity Ingestion Engine (Google Local Relevance).
        Dynamically weaves high-intent wholesale search entities (product SKUs, brands,
        -18°C cold chain, and Sundupalli Road landmark) into owner responses.
        Google's local algorithm indexes owner review replies for Google Maps search queries.
        """
        comment_lower = (review.comment or "").lower()
        author = review.author_name or "Valued Partner"

        # Detect specific commercial product categories
        is_cheese = any(w in comment_lower for w in ["cheese", "mozzarella", "milky", "dairy", "pizza"])
        is_fries = any(w in comment_lower for w in ["fries", "french", "potato", "crispy"])
        is_momos_nonveg = any(w in comment_lower for w in ["momo", "nugget", "chicken", "patty", "burger", "triken"])
        is_packaging = any(w in comment_lower for w in ["box", "boxes", "packaging", "paper", "ogr", "wrap", "container"])
        is_general_frozen = any(w in comment_lower for w in ["frozen", "cold", "fresh", "stock", "quality", "taste"])

        if review.is_complaint:
            english = (
                f"Thank you {author} for bringing this to our personal attention. At RAIS Agencies, we maintain strict "
                f"-18°C cold-chain standards and daily wholesale order accuracy for all Rayachoty food businesses. "
                f"Please contact our depot manager directly at 9347453135 so we can rectify this immediately for your kitchen."
            )
            telugu = (
                f"{author} గారు, ఈ విషయాన్ని మా దృష్టికి తెచ్చినందుకు ధన్యవాదాలు. రాయచోటిలోని ఫుడ్ బిజినెస్‌లకు -18°C కోల్డ్-చైన్ నాణ్యత "
                f"మరియు సరైన సమయానికి సరుకు అందించడమే మా బాధ్యత. దయచేసి మా మేనేజర్‌ను 9347453135 లో నేరుగా సంప్రదించండి, మేము వెంటనే పరిష్కరిస్తాము."
            )
        elif is_cheese:
            english = (
                f"Thank you {author} for your trusted partnership! RAIS Agencies is proud to be Rayachoty's direct wholesale source "
                f"for Milky Mist commercial diced mozzarella cheese, 3-ply corrugated pizza boxes, and dairy supplies. "
                f"Our Sundupalli Road depot ensures daily fresh stock for cafes and pizzerias across Annamayya district."
            )
            telugu = (
                f"{author} గారు, మీ విలువైన భాగస్వామ్యానికి ధన్యవాదాలు! రాయచోటిలోని పిజ్జా కిచెన్‌లు మరియు కేఫ్‌లకు మిల్కీ మిస్ట్ మొజారెల్లా చీజ్, "
                f"నాణ్యమైన పిజ్జా బాక్స్‌లు హోల్‌సేల్ రేట్లకే అందించడం మా ప్రత్యేకత. సుండుపల్లి రోడ్డులోని మా డిపోలో ఎల్లప్పుడూ ఫ్రెష్ స్టాక్ సిద్ధంగా ఉంటుంది."
            )
        elif is_fries:
            english = (
                f"Thank you {author} for your great feedback! We are dedicated to providing Rayachoty fast-food kitchens with "
                f"guaranteed -18°C cold-chain supply of Amul 6mm french fries, burger patties, and Del Monte sauces at genuine wholesale rates. "
                f"Always available for instant pickup beside Indel Money Bank on Sundupalli Road."
            )
            telugu = (
                f"{author} గారు, మీ పాజిటివ్ ఫీడ్‌బ్యాక్‌కు ధన్యవాదాలు! రాయచోటి ఫాస్ట్ ఫుడ్ సెంటర్లకు అముల్ ఫ్రెంచ్ ఫ్రైస్, బర్గర్ ప్యాటీస్ "
                f"మరియు సాస్‌లను -18°C కోల్డ్-చైన్ భద్రతతో హోల్‌సేల్ ధరలకే అందిస్తున్నాము. సుండుపల్లి రోడ్డు ఇండెల్ బ్యాంక్ పక్కన మా వద్ద రెడీ స్టాక్ లభిస్తుంది."
            )
        elif is_momos_nonveg:
            english = (
                f"Thank you {author} for your positive review! RAIS Agencies is committed to supplying Rayachoty and Annamayya district with "
                f"ready-to-steam Triken chicken momos, crispy chicken nuggets, and frozen snacks with uncompromised deep-freezer quality. "
                f"Looking forward to serving your commercial kitchen regularly!"
            )
            telugu = (
                f"{author} గారు, మీ అమూల్యమైన రివ్యూకు ధన్యవాదాలు! రాయచోటిలోని రెస్టారెంట్లు మరియు స్నాక్ పాయింట్లకు ట్రైకెన్ చికెన్ మోమోస్, "
                f"నగ్గెట్స్ మరియు నాన్‌వెజ్ స్నాక్స్ నాణ్యమైన డీప్-ఫ్రీజర్ భద్రతతో నిరంతరం సరఫరా చేయడమే మా లక్ష్యం."
            )
        elif is_packaging:
            english = (
                f"Thank you {author} for choosing RAIS Agencies! We take pride in being Rayachoty's authorized supplier for "
                f"certified 40 GSM OGR food wrapping butter paper, heavy 3-ply corrugated pizza takeaway boxes, and disposable containers. "
                f"Bulk master bundles are always in stock at our Sundupalli Road warehouse."
            )
            telugu = (
                f"{author} గారు, రైస్ ఏజెన్సీస్‌ను ఎంచుకున్నందుకు ధన్యవాదాలు! రాయచోటిలో సర్టిఫైడ్ OGR బటర్ పేపర్, 3-ప్లై పిజ్జా బాక్స్‌లు "
                f"మరియు ఫుడ్ ప్యాకేజింగ్ మెటీరియల్స్ హోల్‌సేల్ బండిల్స్ రూపంలో మా సుండుపల్లి రోడ్డు వేర్‌హౌస్‌లో ఎల్లప్పుడూ అందుబాటులో ఉంటాయి."
            )
        else:
            english = (
                f"Thank you {author} for your trusted partnership with RAIS Agencies Rayachoty! As the central wholesale distribution "
                f"hub on Sundupalli Road (beside Indel Money Bank), we guarantee -18°C cold-chain frozen snacks, commercial cheese, and "
                f"food packaging with prompt daily dispatch across Annamayya district."
            )
            telugu = (
                f"{author} గారు, రైస్ ఏజెన్సీస్ రాయచోటిపై మీ నమ్మకానికి ధన్యవాదాలు! సుండుపల్లి రోడ్డులోని (ఇండెల్ బ్యాంక్ పక్కన) మా హోల్‌సేల్ హబ్ ద్వారా "
                f"-18°C కోల్డ్-చైన్ ఫ్రోజెన్ ఫుడ్స్, మిల్కీ మిస్ట్ చీజ్ మరియు ప్యాకేజింగ్ సరుకులను అన్నమయ్య జిల్లా అంతటా సమయానికి అందిస్తున్నాము."
            )

        return {"english": english, "telugu": telugu}

    async def create_test_review(
        self,
        db: AsyncSession,
        author_name: str = "Rayachoty Cafe Partner",
        rating: int = 5,
        comment: str = "Excellent wholesale service! Timely delivery of Amul french fries and Milky Mist cheese in Rayachoty."
    ) -> Review:
        """Creates an authentic review with bilingual response drafts for client workflow demonstration."""
        import uuid
        review_id = f"test-rev-{uuid.uuid4().hex[:8]}"
        analysis = self.classify_sentiment(rating, comment)
        
        new_rev = Review(
            google_review_id=review_id,
            author_name=author_name,
            rating=rating,
            comment=comment,
            create_time=datetime.now(timezone.utc),
            sentiment=analysis["sentiment"],
            is_complaint=analysis["is_complaint"],
            has_replied=False,
            origin=ReviewOrigin.LOCAL_DIRECT
        )
        db.add(new_rev)
        await db.flush()

        draft = self.generate_response_draft(new_rev)
        draft_obj = ReviewReplyDraft(
            review_id=new_rev.id,
            reply_english=draft["english"],
            reply_telugu=draft["telugu"],
            is_approved=False,
            status=ReplyStatus.PENDING_APPROVAL.value
        )
        db.add(draft_obj)
        await db.commit()
        return new_rev

    async def approve_and_publish_reply(
        self,
        db: AsyncSession,
        draft_id: int,
        custom_reply_text: Optional[str] = None,
        approver_name: str = "Administrator"
    ) -> Dict[str, Any]:
        """
        CRITICAL APPROVAL GATE:
        Reviews CANNOT be published to Google without explicit human invocation of this method.
        Directly enforces Google Business Profile policy compliance.
        """
        stmt = select(ReviewReplyDraft).where(ReviewReplyDraft.id == draft_id)
        res = await db.execute(stmt)
        draft = res.scalar_one_or_none()

        if not draft:
            raise ValueError(f"Review draft ID {draft_id} not found.")

        # Fetch parent review
        stmt_rev = select(Review).where(Review.id == draft.review_id)
        res_rev = await db.execute(stmt_rev)
        review = res_rev.scalar_one_or_none()

        if not review:
            raise ValueError("Associated review record not found.")

        now = datetime.now(timezone.utc)
        reply_to_send = custom_reply_text or draft.reply_english or ""
        draft.reply_english = reply_to_send
        draft.is_approved = True
        draft.approved_by = approver_name
        draft.approved_at = now

        # Publish to Google Business Profile via GBPService
        publish_res = await gbp_service.reply_to_review(
            location_id=None,
            review_id=review.google_review_id,
            reply_text=reply_to_send,
            db=db
        )

        draft.status = publish_res.get("status", ReplyStatus.APPROVED_NOT_PUBLISHED.value)
        review.has_replied = True
        if draft.status == ReplyStatus.PUBLISHED_TO_GOOGLE.value:
            draft.published_at = now

        # Audit log explicit human approval
        await log_audit(
            db=db,
            action="APPROVE_REVIEW_REPLY",
            resource_type="ReviewReplyDraft",
            resource_id=str(draft.id),
            actor=approver_name,
            details={
                "review_id": review.id,
                "google_review_id": review.google_review_id,
                "author_name": review.author_name,
                "rating": review.rating,
                "published_status": draft.status,
                "text_snippet": reply_to_send[:60]
            }
        )

        await db.commit()
        return publish_res

review_service = ReviewService()
