import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.models.entities import (
    Campaign, CampaignPost, PublishingJob, PostStatus, AutomationSetting
)
from app.core.audit import log_audit
from app.services.gbp_service import gbp_service

class SchedulerService:
    """Persistent Publishing Engine with Idempotency and Emergency Kill-Switch."""

    async def check_kill_switch(self, db: AsyncSession) -> bool:
        """Returns True if emergency kill-switch is active (blocking all publishing)."""
        stmt = select(AutomationSetting).limit(1)
        res = await db.execute(stmt)
        setting = res.scalar_one_or_none()
        if setting and setting.emergency_kill_switch:
            return True
        return False

    async def set_kill_switch(self, db: AsyncSession, active: bool, actor: str = "Admin") -> bool:
        """Toggles the emergency kill switch."""
        stmt = select(AutomationSetting).limit(1)
        res = await db.execute(stmt)
        setting = res.scalar_one_or_none()
        if not setting:
            setting = AutomationSetting(emergency_kill_switch=active)
            db.add(setting)
        else:
            setting.emergency_kill_switch = active
        await db.commit()

        await log_audit(
            db=db,
            action="EMERGENCY_KILL_SWITCH_TOGGLED",
            resource_type="AUTOMATION",
            actor=actor,
            details={"active": active}
        )
        return active

    async def approve_and_schedule_campaign(
        self,
        db: AsyncSession,
        campaign_id: int,
        start_date: datetime = None,
        frequency_days: List[int] = None, # 0=Monday, 2=Wednesday, 4=Friday, 6=Sunday
        actor: str = "Admin"
    ) -> Dict[str, Any]:
        """
        Explicit user approval gate.
        Campaign posts transition from DRAFT to SCHEDULED only when user approves.
        """
        stmt = select(Campaign).where(Campaign.id == campaign_id)
        res = await db.execute(stmt)
        campaign = res.scalar_one_or_none()
        if not campaign:
            raise ValueError(f"Campaign {campaign_id} not found.")

        # Update campaign state
        campaign.is_approved_by_user = True
        campaign.approved_at = datetime.now(timezone.utc)
        campaign.status = PostStatus.APPROVED

        # Load posts
        p_stmt = select(CampaignPost).where(CampaignPost.campaign_id == campaign_id)
        p_res = await db.execute(p_stmt)
        posts = p_res.scalars().all()

        current_time = start_date or datetime.now(timezone.utc)
        scheduled_count = 0

        for idx, post in enumerate(posts):
            post.status = PostStatus.SCHEDULED
            # Schedule each post forward
            post_time = current_time + timedelta(days=idx * 2, hours=10, minutes=30)
            post.scheduled_for = post_time
            
            # Idempotency token creation
            idempotency_token = f"rais_job_{campaign_id}_{post.id}_{uuid.uuid4().hex[:8]}"
            post.idempotency_key = idempotency_token

            # Create publishing job record
            job = PublishingJob(
                post_id=post.id,
                scheduled_time=post_time,
                status=PostStatus.SCHEDULED,
                idempotency_token=idempotency_token
            )
            db.add(job)
            scheduled_count += 1

        await db.commit()

        await log_audit(
            db=db,
            action="CAMPAIGN_APPROVED_AND_SCHEDULED",
            resource_type="CAMPAIGN",
            resource_id=str(campaign_id),
            actor=actor,
            details={"posts_scheduled": scheduled_count}
        )

        return {
            "campaign_id": campaign_id,
            "status": "SCHEDULED",
            "scheduled_posts": scheduled_count
        }

    async def execute_publishing_cycle(self, db: AsyncSession, location_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Executes ready publishing jobs whose scheduled_time <= now.
        Guarantees idempotency and respects emergency kill switch.
        Strict Authenticity Rules:
        - Real mode sets post.status = PUBLISHED only upon verified Google API response.
        - Mock mode never marks post as published to Google.
        """
        # 1. Kill-Switch Check
        if await self.check_kill_switch(db):
            return {
                "status": "HALTED",
                "message": "Emergency kill switch is active. Publishing is blocked.",
                "published_count": 0,
                "simulated_count": 0,
                "failed_count": 0,
                "skipped_count": 0
            }

        now = datetime.now(timezone.utc)

        # 2. Query pending jobs
        stmt = select(PublishingJob).where(
            PublishingJob.status == PostStatus.SCHEDULED,
            PublishingJob.scheduled_time <= now
        ).limit(10)
        res = await db.execute(stmt)
        jobs = res.scalars().all()

        published_count = 0
        simulated_count = 0
        failed_count = 0
        skipped_count = 0

        for job in jobs:
            # Query post
            p_stmt = select(CampaignPost).where(CampaignPost.id == job.post_id)
            p_res = await db.execute(p_stmt)
            post = p_res.scalar_one_or_none()

            # IDEMPOTENCY SAFETY: Check if already published or processed
            if not post or post.published_at is not None or job.published_time is not None:
                job.status = PostStatus.PUBLISHED
                skipped_count += 1
                continue

            try:
                # Combine English & Telugu copy
                summary_text = post.headline + "\n\n" + post.content_english
                if post.content_telugu:
                    summary_text += "\n\n" + post.content_telugu

                post_payload = {
                    "summary": summary_text,
                    "call_to_action": post.call_to_action,
                    "cta_url": f"https://wa.me/919347453135"
                }

                # Publish via GBP Service (passes db session)
                api_result = await gbp_service.create_local_post(location_id, post_payload, db=db)

                is_live_pub = bool(api_result.get("is_published_to_google", False) and api_result.get("state") == "LIVE")

                if is_live_pub:
                    post.status = PostStatus.PUBLISHED
                    post.published_at = datetime.now(timezone.utc)
                    post.google_post_id = api_result.get("name")
                    job.status = PostStatus.PUBLISHED
                    job.published_time = datetime.now(timezone.utc)
                    published_count += 1
                else:
                    # Simulated / Demo mode: Never record as PUBLISHED to Google
                    post.status = PostStatus.DRAFT
                    post.published_at = None
                    post.google_post_id = None
                    job.status = PostStatus.PUBLISHED  # Mark job finished to ensure cycle idempotency
                    job.published_time = datetime.now(timezone.utc)
                    simulated_count += 1

                await log_audit(
                    db=db,
                    action="POST_PUBLISHED_TO_GOOGLE" if is_live_pub else "POST_SIMULATED_DEMO_EXECUTION",
                    resource_type="CAMPAIGN_POST",
                    resource_id=str(post.id),
                    details={
                        "google_post_id": post.google_post_id,
                        "is_live_published": is_live_pub,
                        "state": api_result.get("state")
                    }
                )

            except Exception as e:
                job.retry_count += 1
                job.last_error = str(e)
                if job.retry_count >= job.max_retries:
                    job.status = PostStatus.FAILED
                    post.status = PostStatus.FAILED
                failed_count += 1

        await db.commit()

        return {
            "status": "SUCCESS",
            "published_count": published_count,
            "simulated_count": simulated_count,
            "failed_count": failed_count,
            "skipped_count": skipped_count
        }

scheduler_service = SchedulerService()
