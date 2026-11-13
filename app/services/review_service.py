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

        for r in raw_reviews:
            r_id = r.get("review_id")
            if not r_id:
                continue
            stmt = select(Review).where(Review.google_review_id == r_id)
            res = await db.execute(stmt)
            existing = res.scalar_one_or_none()

            if not existing:
                analysis = self.classify_sentiment(r.get("star_rating", 5), r.get("comment"))
                new_rev = Review(
                    google_review_id=r_id,
                    author_name=r.get("reviewer", {}).get("display_name", "Valued Customer"),
                    rating=r.get("star_rating", 5),
                    comment=r.get("comment"),
                    create_time=datetime.fromisoformat(r.get("create_time")),
                    sentiment=analysis["sentiment"],
                    is_complaint=analysis["is_complaint"],
                    has_replied=bool(r.get("review_reply")),
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

        await db.commit()
        return imported_count

    def generate_response_draft(self, review: Review) -> Dict[str, str]:
        """Generates contextual draft responses in English & Telugu."""
        if review.sentiment == SentimentType.POSITIVE:
            english = (
                f"Thank you for your feedback! At RAIS Agencies, we are committed to providing Rayachoty's "
                f"commercial kitchens with guaranteed cold-chain quality and reliable wholesale supplies. "
                f"We look forward to serving your kitchen again!"
            )
            telugu = (
                f"మీ విలువైన ఫీడ్‌బ్యాక్‌కు ధన్యవాదాలు! రాయచోటిలోని హోటళ్లు మరియు కేఫ్‌లకు ఉత్తమ హోల్‌సేల్ సేవలు "
                f"మరియు క్వాలిటీ ఫ్రోజెన్ ఫుడ్స్ అందించడమే మా లక్ష్యం. ధన్యవాదాలు!"
            )
        elif review.is_complaint:
            english = (
                f"Thank you for bringing this to our attention. We take product quality and delivery punctuality seriously. "
                f"Please reach out directly to our management desk at 9347453135 so we can resolve this immediately for your kitchen."
            )
            telugu = (
                f"ఈ విషయాన్ని మా దృష్టికి తెచ్చినందుకు ధన్యవాదాలు. దయచేసి మా మేనేజ్‌మెంట్ డెస్క్ 9347453135 నంబర్‌ను "
                f"సంప్రదించండి, మేము వెంటనే పరిష్కరిస్తాము."
            )
        else:
            english = (
                f"Thank you for reaching out to RAIS Agencies Rayachoty! For complete wholesale catalog and pricing, "
                f"please connect directly with our B2B desk at 9347453135."
            )
            telugu = (
                f"రైస్ ఏజెన్సీస్ రాయచోటిని సంప్రదించినందుకు ధన్యవాదాలు! పూర్తి హోల్‌సేల్ క్యాటలాగ్ కొరకు 9347453135 వాట్సాప్ నంబర్‌ను సంప్రదించండి."
            )
        return {"english": english, "telugu": telugu}

    async def approve_and_publish_reply(
        self,
        db: AsyncSession,
        draft_id: int,
        custom_reply_text: Optional[str] = None,
        approver_name: str = "Admin",
        location_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        MANDATORY EXPLICIT APPROVAL WORKFLOW:
        A review reply can NEVER be published without explicit approval by an administrator.
        """
        stmt = select(ReviewReplyDraft).where(ReviewReplyDraft.id == draft_id)
        res = await db.execute(stmt)
        draft = res.scalar_one_or_none()
        if not draft:
            raise ValueError(f"Reply draft {draft_id} not found.")

        # Query parent review
        r_stmt = select(Review).where(Review.id == draft.review_id)
        r_res = await db.execute(r_stmt)
        review = r_res.scalar_one_or_none()

        reply_to_send = custom_reply_text or draft.reply_english

        # Push to Google Business Profile API (passes db session)
        try:
            api_result = await gbp_service.reply_to_review(location_id, review.google_review_id, reply_to_send, db=db)
            is_live_pub = bool(api_result.get("is_published_to_google") and not api_result.get("is_simulated"))

            if is_live_pub:
                draft.status = ReplyStatus.PUBLISHED_TO_GOOGLE.value
                draft.published_at = datetime.now(timezone.utc)
                review.has_replied = True
                action = "REVIEW_REPLY_PUBLISHED_TO_GOOGLE"
            elif api_result.get("is_simulated") or api_result.get("status") == "SIMULATED_DEMO_APPROVAL":
                draft.status = ReplyStatus.SIMULATED_DEMO_APPROVAL.value
                draft.published_at = None
                review.has_replied = True
                action = "REVIEW_REPLY_SIMULATED_DEMO_APPROVAL"
            else:
                draft.status = ReplyStatus.APPROVED_NOT_PUBLISHED.value
                draft.published_at = None
                action = "REVIEW_REPLY_APPROVED_NOT_PUBLISHED"
        except Exception as e:
            draft.status = ReplyStatus.PUBLICATION_FAILED.value
            draft.published_at = None
            action = "REVIEW_REPLY_PUBLICATION_FAILED"
            raise e
        finally:
            draft.is_approved = True
            draft.approved_by = approver_name
            draft.approved_at = datetime.now(timezone.utc)
            await db.commit()

        await log_audit(
            db=db,
            action=action,
            resource_type="REVIEW",
            resource_id=str(review.id),
            actor=approver_name,
            details={"reply_text": reply_to_send, "status": draft.status}
        )

        return {
            "status": draft.status,
            "review_id": review.id,
            "reply_text": reply_to_send
        }

review_service = ReviewService()
