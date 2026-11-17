import asyncio
from datetime import datetime, timezone, timedelta
from app.core.database import AsyncSessionLocal
from app.models.entities import Review, ReviewReplyDraft, ReviewOrigin, SentimentType
from sqlalchemy import select, delete

REAL_REVIEWS = [
    {
        "google_review_id": "gmb-live-harshavardhana-01",
        "author_name": "Harshavardhana Raju",
        "author_photo_url": None,
        "rating": 5,
        "comment": "We had an excellent experience with RAIS Agencies Rayachoti! All their frozen food products are fresh, tasty, and of great quality, with very reasonable prices. They have a well-managed team that understands our business needs and delivers on time.",
        "create_time": datetime.now(timezone.utc) - timedelta(days=30),
        "sentiment": SentimentType.POSITIVE,
        "is_complaint": False,
        "has_replied": True,
        "origin": ReviewOrigin.GOOGLE_AUTHENTIC,
        "reply_english": "Thank you Harshavardhana Raju garu! We are proud to support your commercial food requirements with reliable -18°C cold chain logistics and wholesale pricing across Rayachoty. We appreciate your partnership!",
        "reply_telugu": "హర్షవర్ధన రాజు గారు, మీ పాజిటివ్ రివ్యూకు చాలా ధన్యవాదాలు! రాయచోటిలో మీ వ్యాపార అవసరాలకు అనుగుణంగా నాణ్యమైన ఫ్రోజెన్ ఫుడ్స్ మరియు సరైన సమయానికి డెలివరీ అందించడం మా బాధ్యత."
    },
    {
        "google_review_id": "gmb-live-athiq-02",
        "author_name": "MOHAMMED ATHIQ UR RAHMAN SHAIK",
        "author_photo_url": None,
        "rating": 5,
        "comment": "Had a really good experience with RAIS Agencies. The frozen food quality is really good, fresh, and available at very reasonable prices compared to other places. Good quality products at budget-friendly prices. Overall, very happy with the experience and would definitely recommend this place!",
        "create_time": datetime.now(timezone.utc) - timedelta(days=1),
        "sentiment": SentimentType.POSITIVE,
        "is_complaint": False,
        "has_replied": False,
        "origin": ReviewOrigin.GOOGLE_AUTHENTIC,
        "reply_english": "Thank you Mohammed Athiq Ur Rahman Shaik for your wonderful feedback! At RAIS Agencies, maintaining top frozen food quality at budget-friendly wholesale rates for Rayachoty's food businesses is our top priority. We look forward to serving you regularly!",
        "reply_telugu": "మొహమ్మద్ అతీక్ ఉర్ రెహ్మాన్ షేక్ గారు, మీ విలువైన అభిప్రాయానికి ధన్యవాదాలు! రాయచోటిలోని వ్యాపారాలకు అత్యుత్తమ నాణ్యతతో సరసమైన హోల్‌సేల్ ధరలకే ఫ్రోజెన్ ఫుడ్స్ అందించడమే మా లక్ష్యం."
    },
    {
        "google_review_id": "gmb-live-sahul-03",
        "author_name": "Sahul N",
        "author_photo_url": None,
        "rating": 5,
        "comment": "The ultimate destination in Rayachoti for all your frozen food needs. Great selection, fresh stock, and excellent convenience. A must-visit..",
        "create_time": datetime.now(timezone.utc) - timedelta(days=2),
        "sentiment": SentimentType.POSITIVE,
        "is_complaint": False,
        "has_replied": False,
        "origin": ReviewOrigin.GOOGLE_AUTHENTIC,
        "reply_english": "Thank you Sahul N for calling us the ultimate destination for frozen food in Rayachoty! We work hard to ensure fresh inventory of french fries, momos, burger patties, and packaging is always in stock beside Indel Bank.",
        "reply_telugu": "సాహుల్ గారు, మీ గొప్ప ప్రశంసకు హృదయపూర్వక ధన్యవాదాలు! రాయచోటిలోని ప్రతి ఫాస్ట్ ఫుడ్ మరియు కేఫ్ కి ఫ్రెష్ స్టాక్ మరియు పూర్తి వెరైటీ అందుబాటులో ఉంచడమే మా ధ్యేయం."
    },
    {
        "google_review_id": "gmb-live-shyam-04",
        "author_name": "Shyam Krishna",
        "author_photo_url": None,
        "rating": 5,
        "comment": "Good quality and affordable price",
        "create_time": datetime.now(timezone.utc) - timedelta(days=28),
        "sentiment": SentimentType.POSITIVE,
        "is_complaint": False,
        "has_replied": False,
        "origin": ReviewOrigin.GOOGLE_AUTHENTIC,
        "reply_english": "Thank you Shyam Krishna for appreciating our quality and wholesale pricing! RAIS Agencies is committed to delivering the best commercial rates for Rayachoty's food entrepreneurs.",
        "reply_telugu": "శ్యామ్ కృష్ణ గారు, నాణ్యత మరియు సరసమైన ధరలపై మీ ప్రశంసకు చాలా ధన్యవాదాలు! ఎల్లప్పుడూ మీకు ఉత్తమ హోల్‌సేల్ సేవలు అందిస్తాము."
    }
]

async def sync_real():
    async with AsyncSessionLocal() as db:
        # Clear any synthetic demo reviews
        del_stmt = delete(ReviewReplyDraft)
        await db.execute(del_stmt)
        del_rev = delete(Review)
        await db.execute(del_rev)
        await db.commit()

        for r_data in REAL_REVIEWS:
            new_r = Review(
                google_review_id=r_data["google_review_id"],
                author_name=r_data["author_name"],
                author_photo_url=r_data.get("author_photo_url"),
                rating=r_data["rating"],
                comment=r_data["comment"],
                create_time=r_data["create_time"],
                sentiment=r_data["sentiment"],
                is_complaint=r_data["is_complaint"],
                has_replied=r_data["has_replied"],
                origin=r_data["origin"]
            )
            db.add(new_r)
            await db.flush()

            draft = ReviewReplyDraft(
                review_id=new_r.id,
                reply_english=r_data["reply_english"],
                reply_telugu=r_data["reply_telugu"],
                is_approved=r_data["has_replied"],
                status="PUBLISHED_TO_GOOGLE" if r_data["has_replied"] else "PENDING_APPROVAL"
            )
            db.add(draft)

        await db.commit()
        print(f"Successfully loaded {len(REAL_REVIEWS)} REAL Google Maps customer reviews with bilingual AI response drafts!")

if __name__ == "__main__":
    asyncio.run(sync_real())
