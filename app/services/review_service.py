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
        """Generates contextual draft responses in English & Telugu."""
        if review.sentiment == SentimentType.POSITIVE:
            english = (
                f"Thank you {review.author_name} for your trusted partnership! At RAIS Agencies, we are committed to providing Rayachoty's "
                f"commercial kitchens with guaranteed -18°C cold-chain quality and reliable wholesale supplies. "
                f"We look forward to serving your kitchen regularly!"
            )
            telugu = (
                f"మీ విలువైన ఫీడ్‌బ్యాక్‌కు ధన్యవాదాలు {review.author_name} గారు! రాయచోటిలోని హోటళ్లు మరియు కేఫ్‌లకు ఉత్తమ హోల్‌సేల్ సేవలు "
                f"మరియు -18°C నాణ్యమైన ఫ్రోజెన్ ఫుడ్స్ అందించడమే మా లక్ష్యం. ధన్యవాదాలు!"
            )
        elif review.is_complaint:
            english = (
                f"Thank you {review.author_name} for bringing this to our attention. We take product quality and delivery punctuality seriously. "
                f"Please reach out directly to our management desk at 9347453135 so we can resolve this immediately for your kitchen."
            )
            telugu = (
                f"ఈ విషయాన్ని మా దృష్టికి తెచ్చినందుకు ధన్యవాదాలు {review.author_name} గారు. దయచేసి మా మేనేజ్‌మెంట్ డెస్క్ 9347453135 నంబర్‌ను "
                f"సంప్రదించండి, మేము వెంటనే పరిష్కరిస్తాము."
            )
        else:
            english = (
                f"Thank you {review.author_name} for reaching out to RAIS Agencies Rayachoty! For complete wholesale catalog and pricing, "
                f"please connect directly with our B2B desk at 9347453135."
            )
            telugu = (
                f"రైస్ ఏజెన్సీస్ రాయచోటిని సంప్రదించినందుకు ధన్యవాదాలు {review.author_name} గారు! పూర్తి హోల్‌సేల్ క్యాటలాగ్ కొరకు 9347453135 వాట్సాప్ నంబర్‌ను సంప్రదించండి."
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
        custom_reply_text: str,
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
        draft.reply_english = custom_reply_text
        draft.is_approved = True
        draft.approved_by = approver_name
        draft.approved_at = now

        # Publish to Google Business Profile via GBPService
        publish_res = await gbp_service.reply_to_review(
            location_id=None,
            review_id=review.google_review_id,
            reply_text=custom_reply_text,
            db=db
        )

        review.has_replied = True
        draft.published_at = now
        draft.status = publish_res.get("status", ReplyStatus.APPROVED_NOT_PUBLISHED.value)

        # Audit log explicit human approval
        await log_audit(
            db=db,
            action="APPROVE_REVIEW_REPLY",
            entity_type="ReviewReplyDraft",
            entity_id=str(draft.id),
            user_id=approver_name,
            details={
                "review_id": review.id,
                "google_review_id": review.google_review_id,
                "author_name": review.author_name,
                "rating": review.rating,
                "published_status": draft.status,
                "text_snippet": custom_reply_text[:60]
            }
        )

        await db.commit()
        return publish_res

review_service = ReviewService()
