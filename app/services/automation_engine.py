import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import log_audit
from app.models.entities import (
    AutomationApproval,
    AutomationSetting,
    B2BLead,
    CatalogSKU,
    CustomerEnquiry,
    CustomerInteraction,
    LeadStatus,
    WorkflowDefinition,
    WorkflowExecution,
    WorkflowExecutionStatus,
    WorkflowExecutionStep,
)


SUPPORTED_TRIGGERS = [
    "new_lead",
    "new_customer",
    "new_product",
    "stock_arrival",
    "new_enquiry",
    "new_review",
    "new_media_upload",
    "campaign_approval",
    "publishing_completion",
    "publishing_failure",
    "customer_inactivity",
    "scheduled_time",
    "daily_schedule",
    "weekly_schedule",
    "manual_execution",
]

DEFAULT_WORKFLOWS = [
    {
        "slug": "lead-qualification-outreach",
        "name": "B2B Lead Qualification & Draft Outreach",
        "description": "Scores new B2B leads, assigns follow-up date, prepares a personalized WhatsApp draft, and pauses for human approval before sending.",
        "trigger_type": "new_lead",
        "conditions": [],
        "actions": [
            {"type": "score_lead", "name": "Score & Segment Lead"},
            {"type": "create_followup_task", "name": "Schedule 24h Follow-Up", "hours": 24},
            {"type": "prepare_whatsapp_draft", "name": "Prepare Bilingual WhatsApp Draft"},
            {"type": "require_approval", "name": "Await Admin Approval Before Dispatch"},
        ],
        "approval_required": True,
        "schedule_cron": None,
    },
    {
        "slug": "stock-arrival-promo",
        "name": "New Stock Arrival -> Campaign Draft",
        "description": "When a catalog SKU is marked back in stock or added, generates a bilingual promotional draft for review.",
        "trigger_type": "stock_arrival",
        "conditions": [],
        "actions": [
            {"type": "generate_ai_content", "name": "Generate Bilingual Product Promo"},
            {"type": "require_approval", "name": "Await Campaign Publishing Approval"},
        ],
        "approval_required": True,
        "schedule_cron": None,
    },
    {
        "slug": "enquiry-intake-triage",
        "name": "Inbound Enquiry Triage & Quotation Prep",
        "description": "Matches inbound enquiry to CRM, checks verified SKU catalogue, prepares response draft, and logs interaction.",
        "trigger_type": "new_enquiry",
        "conditions": [],
        "actions": [
            {"type": "notify_admin", "name": "Log Enquiry Alert in Audit Trail"},
            {"type": "prepare_whatsapp_draft", "name": "Prepare Catalogue Response Draft"},
        ],
        "approval_required": False,
        "schedule_cron": None,
    },
    {
        "slug": "daily-social-autopilot",
        "name": "Daily Drive -> YT/IG/FB Auto-Pilot",
        "description": "Scans configured Google Drive folder and dispatches queued promotional clips across YouTube Shorts, Instagram Reels, Facebook, and scheduled GBP posts.",
        "trigger_type": "daily_schedule",
        "conditions": [],
        "actions": [
            {"type": "sync_and_autopilot_drive", "name": "Run Drive -> YT/IG/FB Auto-Pilot"},
            {"type": "run_gbp_publish_cycle", "name": "Process Scheduled GBP Queue"},
            {"type": "notify_admin", "name": "Record Daily Auto-Pilot Run"},
        ],
        "approval_required": False,
        "schedule_cron": "0 10 * * *",
    },
    {
        "slug": "weekly-seo-competitor-audit",
        "name": "Weekly SEO & Competitor Snapshot Check",
        "description": "Runs periodic SEO completeness audit, checks competitor websites, and syncs reviews.",
        "trigger_type": "weekly_schedule",
        "conditions": [],
        "actions": [
            {"type": "run_seo_competitor_check", "name": "Check Competitor Websites & SEO"},
            {"type": "sync_reviews", "name": "Sync Latest Google Reviews"},
            {"type": "notify_admin", "name": "Log Weekly SEO Audit Check"},
        ],
        "approval_required": False,
        "schedule_cron": "0 9 * * 1",
    },
]


def _evaluate_condition(cond: Dict[str, Any], payload: Dict[str, Any]) -> bool:
    field = cond.get("field")
    op = (cond.get("operator") or "equals").lower()
    expected = cond.get("value")
    if not field:
        return True
    actual = payload.get(field)
    if op == "exists":
        return actual is not None and str(actual).strip() != ""
    if op == "equals":
        return str(actual or "").strip().lower() == str(expected or "").strip().lower()
    if op == "contains":
        return str(expected or "").strip().lower() in str(actual or "").strip().lower()
    if op == "in" and isinstance(expected, list):
        return str(actual or "").strip().lower() in [str(x).strip().lower() for x in expected]
    if op == "gt":
        try:
            return float(actual) > float(expected)
        except (TypeError, ValueError):
            return False
    if op == "lt":
        try:
            return float(actual) < float(expected)
        except (TypeError, ValueError):
            return False
    return True


def compute_lead_score(lead: B2BLead) -> tuple[int, str]:
    score = 40
    btype = (lead.business_type or "").lower()
    loc = (lead.location or "").lower()
    if any(k in btype for k in ("cafe", "qsr", "pizza", "burger", "restaurant")):
        score += 25
    elif any(k in btype for k in ("bakery", "hotel", "catering")):
        score += 20
    if any(k in loc for k in ("rayachoty", "kadiri", "rajampet", "madanapalle", "kadapa")):
        score += 15
    if lead.phone and len("".join(c for c in lead.phone if c.isdigit())) >= 10:
        score += 10
    if lead.product_interest and len(lead.product_interest.strip()) > 3:
        score += 10
    score = min(score, 100)
    segment = "Hot Commercial" if score >= 80 else ("Warm B2B" if score >= 60 else "General B2B")
    return score, segment


def compute_next_run_at(trigger_type: str, schedule_cron: Optional[str], base_dt: Optional[datetime] = None) -> Optional[datetime]:
    """Computes the next UTC execution timestamp for scheduled workflows."""
    now = base_dt or datetime.now(timezone.utc)
    if trigger_type == "daily_schedule":
        hour = 10
        minute = 0
        if schedule_cron:
            parts = schedule_cron.strip().split()
            if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                minute, hour = int(parts[0]), int(parts[1])
        # Interpret configured hour as IST (UTC+5:30)
        ist_offset = timedelta(hours=5, minutes=30)
        now_ist = now + ist_offset
        candidate_ist = now_ist.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate_ist <= now_ist:
            candidate_ist += timedelta(days=1)
        return candidate_ist - ist_offset
    if trigger_type == "weekly_schedule":
        return now + timedelta(days=7)
    if trigger_type == "scheduled_time":
        return now + timedelta(hours=1)
    return None


class AutomationEngine:
    async def ensure_default_workflows(self, db: AsyncSession) -> None:
        existing = {
            w.slug: w
            for w in (await db.execute(select(WorkflowDefinition))).scalars().all()
        }
        changed = False
        for wf in DEFAULT_WORKFLOWS:
            if wf["slug"] not in existing:
                next_dt = compute_next_run_at(wf["trigger_type"], wf["schedule_cron"])
                db.add(
                    WorkflowDefinition(
                        slug=wf["slug"],
                        name=wf["name"],
                        description=wf["description"],
                        trigger_type=wf["trigger_type"],
                        conditions_json=json.dumps(wf["conditions"]),
                        actions_json=json.dumps(wf["actions"]),
                        approval_required=wf["approval_required"],
                        schedule_cron=wf["schedule_cron"],
                        next_run_at=next_dt,
                        is_active=True,
                        is_paused=False,
                    )
                )
                changed = True
            else:
                cur = existing[wf["slug"]]
                if cur.trigger_type in ("daily_schedule", "weekly_schedule", "scheduled_time") and cur.next_run_at is None:
                    cur.next_run_at = compute_next_run_at(cur.trigger_type, cur.schedule_cron)
                    changed = True
        if changed:
            await db.commit()

    async def trigger_event(
        self,
        db: AsyncSession,
        trigger_type: str,
        payload: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> List[WorkflowExecution]:
        await self.ensure_default_workflows(db)
        payload = payload or {}
        workflows = list(
            (
                await db.execute(
                    select(WorkflowDefinition).where(
                        WorkflowDefinition.trigger_type == trigger_type,
                        WorkflowDefinition.is_active == True,
                        WorkflowDefinition.is_paused == False,
                    )
                )
            )
            .scalars()
            .all()
        )
        executions: List[WorkflowExecution] = []
        for wf in workflows:
            key = f"{wf.slug}:{idempotency_key}" if idempotency_key else None
            ex = await self.execute_workflow(db, wf, trigger_type, payload, idempotency_key=key)
            executions.append(ex)
        return executions

    async def execute_workflow(
        self,
        db: AsyncSession,
        workflow: WorkflowDefinition,
        trigger_type: str,
        payload: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        start_from_step: int = 0,
        existing_execution: Optional[WorkflowExecution] = None,
    ) -> WorkflowExecution:
        payload = payload or {}

        # 1. Check emergency kill switch
        setting = (await db.execute(select(AutomationSetting).limit(1))).scalar_one_or_none()
        if setting and setting.emergency_kill_switch:
            ex = WorkflowExecution(
                execution_uid=str(uuid.uuid4()),
                workflow_id=workflow.id,
                trigger_type=trigger_type,
                status=WorkflowExecutionStatus.CANCELLED,
                idempotency_key=idempotency_key,
                input_json=json.dumps(payload),
                output_json=json.dumps({"reason": "Emergency Kill Switch is active"}),
                error_message="Blocked by Emergency Kill Switch",
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            )
            db.add(ex)
            await db.commit()
            await db.refresh(ex)
            return ex

        # 2. Idempotency check
        if idempotency_key and existing_execution is None:
            prior = (
                await db.execute(
                    select(WorkflowExecution).where(WorkflowExecution.idempotency_key == idempotency_key)
                )
            ).scalar_one_or_none()
            if prior:
                return prior

        # 3. Condition evaluation
        conditions = json.loads(workflow.conditions_json or "[]")
        for cond in conditions:
            if not _evaluate_condition(cond, payload):
                ex = WorkflowExecution(
                    execution_uid=str(uuid.uuid4()),
                    workflow_id=workflow.id,
                    trigger_type=trigger_type,
                    status=WorkflowExecutionStatus.CANCELLED,
                    idempotency_key=idempotency_key,
                    input_json=json.dumps(payload),
                    output_json=json.dumps({"skipped": True, "reason": "Workflow condition not matched"}),
                    started_at=datetime.now(timezone.utc),
                    completed_at=datetime.now(timezone.utc),
                )
                db.add(ex)
                await db.commit()
                await db.refresh(ex)
                return ex

        # 4. Create or reuse execution record with lock token
        now = datetime.now(timezone.utc)
        lock_token = str(uuid.uuid4())[:16]
        if existing_execution is None:
            retry_cfg = json.loads(workflow.retry_policy_json or "{}")
            ex = WorkflowExecution(
                execution_uid=str(uuid.uuid4()),
                workflow_id=workflow.id,
                trigger_type=trigger_type,
                status=WorkflowExecutionStatus.RUNNING,
                idempotency_key=idempotency_key,
                lock_token=lock_token,
                input_json=json.dumps(payload),
                attempt_count=1,
                max_attempts=int(retry_cfg.get("max_attempts", 3)),
                started_at=now,
            )
            db.add(ex)
            await db.commit()
            await db.refresh(ex)
        else:
            ex = existing_execution
            ex.status = WorkflowExecutionStatus.RUNNING
            ex.lock_token = lock_token
            ex.attempt_count += 1
            ex.error_message = None
            await db.commit()

        actions = json.loads(workflow.actions_json or "[]")
        outputs: Dict[str, Any] = json.loads(ex.output_json or "{}")
        current_step: Optional[WorkflowExecutionStep] = None

        try:
            for idx in range(start_from_step, len(actions)):
                action = actions[idx]
                action_type = action.get("type", "notify_admin")
                step_name = action.get("name") or action_type

                step = WorkflowExecutionStep(
                    execution_id=ex.id,
                    step_index=idx,
                    step_name=step_name,
                    action_type=action_type,
                    status="RUNNING",
                    input_json=json.dumps(action),
                    started_at=datetime.now(timezone.utc),
                )
                db.add(step)
                await db.commit()
                await db.refresh(step)
                current_step = step

                if action_type == "require_approval":
                    step.status = "AWAITING_APPROVAL"
                    step.output_json = json.dumps({"paused_for_approval": True})
                    ex.status = WorkflowExecutionStatus.AWAITING_APPROVAL
                    ex.output_json = json.dumps(outputs)
                    ex.lock_token = None
                    approval = AutomationApproval(
                        execution_id=ex.id,
                        step_id=step.id,
                        title=f"{workflow.name}: {step_name}",
                        description=f"Workflow execution {ex.execution_uid} requires human approval to continue.",
                        payload_json=json.dumps({"payload": payload, "outputs": outputs, "next_step": idx + 1}),
                        status="PENDING",
                    )
                    db.add(approval)
                    await db.commit()
                    await db.refresh(ex)
                    return ex

                step_result = await self._run_action(db, action_type, action, payload, outputs)
                outputs[f"step_{idx}_{action_type}"] = step_result
                step.status = "SUCCEEDED"
                step.output_json = json.dumps(step_result)
                step.completed_at = datetime.now(timezone.utc)
                current_step = None
                await db.commit()

            ex.status = WorkflowExecutionStatus.SUCCEEDED
            ex.output_json = json.dumps(outputs)
            ex.completed_at = datetime.now(timezone.utc)
            ex.lock_token = None
            workflow.last_run_at = datetime.now(timezone.utc)
            if workflow.trigger_type in ("daily_schedule", "weekly_schedule", "scheduled_time"):
                workflow.next_run_at = compute_next_run_at(workflow.trigger_type, workflow.schedule_cron)
            await db.commit()
            await db.refresh(ex)
            return ex
        except Exception as exc:
            if current_step is not None:
                current_step.status = "FAILED"
                current_step.error_message = str(exc)
                current_step.completed_at = datetime.now(timezone.utc)
            ex.status = WorkflowExecutionStatus.FAILED
            ex.error_message = str(exc)
            ex.output_json = json.dumps(outputs)
            ex.completed_at = datetime.now(timezone.utc)
            ex.lock_token = None
            await db.commit()
            await db.refresh(ex)
            return ex

    async def _run_action(
        self,
        db: AsyncSession,
        action_type: str,
        action_cfg: Dict[str, Any],
        payload: Dict[str, Any],
        outputs: Dict[str, Any],
    ) -> Dict[str, Any]:
        if action_type == "score_lead":
            lead_id = payload.get("lead_id")
            if not lead_id:
                return {"skipped": True, "reason": "No lead_id in payload"}
            lead = (await db.execute(select(B2BLead).where(B2BLead.id == int(lead_id)))).scalar_one_or_none()
            if not lead:
                raise ValueError(f"Lead {lead_id} not found")
            score, segment = compute_lead_score(lead)
            lead.lead_score = score
            lead.segment = segment
            if lead.status == LeadStatus.NEW and score >= 70:
                lead.status = LeadStatus.QUALIFIED
            await db.commit()
            return {"lead_id": lead.id, "lead_score": score, "segment": segment, "status": lead.status.value}

        if action_type == "create_followup_task":
            lead_id = payload.get("lead_id")
            if not lead_id:
                return {"skipped": True, "reason": "No lead_id in payload"}
            lead = (await db.execute(select(B2BLead).where(B2BLead.id == int(lead_id)))).scalar_one_or_none()
            if not lead:
                raise ValueError(f"Lead {lead_id} not found")
            hours = int(action_cfg.get("hours", 24))
            followup_dt = datetime.now(timezone.utc) + timedelta(hours=hours)
            lead.next_followup_at = followup_dt
            db.add(
                CustomerInteraction(
                    lead_id=lead.id,
                    channel="AUTOMATION",
                    direction="INTERNAL",
                    summary=f"Follow-up scheduled for {followup_dt.strftime('%Y-%m-%d %H:%M UTC')}",
                    created_by="automation_engine",
                )
            )
            await db.commit()
            return {"lead_id": lead.id, "next_followup_at": followup_dt.isoformat()}

        if action_type == "prepare_whatsapp_draft":
            business = payload.get("business_name") or payload.get("customer_name") or "Partner"
            product = payload.get("product_interest") or payload.get("product_name") or "frozen food & packaging supplies"
            draft = (
                f"Namaste {business}, this is RAIS Agencies (Beside Indel Money Bank, Sundupalli Road, Rayachoty). "
                f"We received your interest in {product}. Reply here or call 9347453135 for today's wholesale carton dispatch."
            )
            enquiry_id = payload.get("enquiry_id")
            if enquiry_id:
                enq = (await db.execute(select(CustomerEnquiry).where(CustomerEnquiry.id == int(enquiry_id)))).scalar_one_or_none()
                if enq:
                    enq.prepared_response = draft
                    await db.commit()
            return {"draft_message": draft}

        if action_type == "generate_ai_content":
            from app.services.ai_content_engine import ai_content_engine

            sku_code = payload.get("sku")
            sku_obj = None
            if sku_code:
                sku_obj = (await db.execute(select(CatalogSKU).where(CatalogSKU.sku == sku_code))).scalar_one_or_none()
            theme = payload.get("theme") or (f"Fresh Stock: {sku_obj.name}" if sku_obj else "Wholesale Cold-Chain Supply")
            res = await ai_content_engine.generate_campaign_post(
                db=db,
                theme=theme,
                target_sku=sku_code,
                language_mode="bilingual",
            )
            return {
                "generation_engine": res.get("generation_engine"),
                "headline": res.get("content", {}).get("headline"),
                "passed_validation": res.get("validation_report", {}).get("is_valid"),
            }

        if action_type == "send_whatsapp_template":
            from app.services.whatsapp_service import whatsapp_service

            phone = payload.get("phone")
            if not phone:
                return {"skipped": True, "reason": "No phone in payload"}
            draft_msg = payload.get("draft_message")
            if not draft_msg:
                for k, v in outputs.items():
                    if k.endswith("_prepare_whatsapp_draft") and isinstance(v, dict) and v.get("draft_message"):
                        draft_msg = v["draft_message"]
                        break
            res = await whatsapp_service.send_text_message(
                db=db,
                phone=phone,
                body=draft_msg or "Hello from RAIS Agencies Rayachoty. Call 9347453135 for wholesale supply.",
                lead_id=payload.get("lead_id"),
                template_name=action_cfg.get("template_name") or payload.get("template_name"),
            )
            if not res.get("sent"):
                raise RuntimeError(res.get("error") or "WhatsApp Cloud API not connected")
            return res

        if action_type == "sync_and_autopilot_drive":
            from app.api.routes_youtube import _run_autopilot_locked
            return await _run_autopilot_locked(db)

        if action_type == "run_gbp_publish_cycle":
            from app.services.scheduler_service import scheduler_service
            return await scheduler_service.execute_publishing_cycle(db)

        if action_type == "sync_reviews":
            from app.services.review_service import review_service
            count = await review_service.sync_reviews_from_gbp(db)
            return {"synced_reviews": count}

        if action_type == "run_seo_competitor_check":
            from app.models.entities import CompetitorSnapshot
            comps = list((await db.execute(select(CompetitorSnapshot))).scalars().all())
            return {"competitors_monitored": len(comps), "checked_at": datetime.now(timezone.utc).isoformat()}

        if action_type == "delay_wait":
            return {"wait_hours": action_cfg.get("hours", 24), "recorded": True}

        # Default: notify_admin
        await log_audit(
            db=db,
            action="WORKFLOW_NOTIFICATION",
            resource_type="WORKFLOW",
            resource_id=str(payload.get("lead_id") or payload.get("sku") or "system"),
            details={"step": action_cfg.get("name", action_type), "payload": payload},
        )
        return {"notified": True}

    async def approve_and_resume(
        self,
        db: AsyncSession,
        approval_id: int,
        reviewer: str,
        notes: Optional[str] = None,
    ) -> WorkflowExecution:
        approval = (
            await db.execute(select(AutomationApproval).where(AutomationApproval.id == approval_id))
        ).scalar_one_or_none()
        if not approval:
            raise ValueError("Approval request not found")
        if approval.status != "PENDING":
            raise ValueError(f"Approval already {approval.status}")

        approval.status = "APPROVED"
        approval.reviewed_by = reviewer
        approval.reviewed_at = datetime.now(timezone.utc)
        approval.decision_notes = notes
        await db.commit()

        ex = (
            await db.execute(select(WorkflowExecution).where(WorkflowExecution.id == approval.execution_id))
        ).scalar_one_or_none()
        wf = (
            await db.execute(select(WorkflowDefinition).where(WorkflowDefinition.id == ex.workflow_id))
        ).scalar_one_or_none()
        meta = json.loads(approval.payload_json or "{}")
        next_step = int(meta.get("next_step", 0))
        payload = meta.get("payload") or json.loads(ex.input_json or "{}")

        return await self.execute_workflow(
            db=db,
            workflow=wf,
            trigger_type=ex.trigger_type,
            payload=payload,
            start_from_step=next_step,
            existing_execution=ex,
        )

    async def reject_approval(
        self,
        db: AsyncSession,
        approval_id: int,
        reviewer: str,
        notes: Optional[str] = None,
    ) -> AutomationApproval:
        approval = (
            await db.execute(select(AutomationApproval).where(AutomationApproval.id == approval_id))
        ).scalar_one_or_none()
        if not approval:
            raise ValueError("Approval request not found")
        approval.status = "REJECTED"
        approval.reviewed_by = reviewer
        approval.reviewed_at = datetime.now(timezone.utc)
        approval.decision_notes = notes
        ex = (
            await db.execute(select(WorkflowExecution).where(WorkflowExecution.id == approval.execution_id))
        ).scalar_one_or_none()
        if ex:
            ex.status = WorkflowExecutionStatus.CANCELLED
            ex.completed_at = datetime.now(timezone.utc)
            ex.error_message = f"Rejected by {reviewer}: {notes or 'No reason provided'}"
        await db.commit()
        await db.refresh(approval)
        return approval

    async def retry_execution(self, db: AsyncSession, execution_id: int) -> WorkflowExecution:
        """Safely retries a failed execution starting from the first failed/incomplete step."""
        ex = (await db.execute(select(WorkflowExecution).where(WorkflowExecution.id == execution_id))).scalar_one_or_none()
        if not ex:
            raise ValueError("Execution not found")
        if ex.lock_token:
            raise RuntimeError("Execution is currently locked by another worker")
        if ex.status not in (WorkflowExecutionStatus.FAILED, WorkflowExecutionStatus.RETRYING):
            raise RuntimeError(f"Only FAILED/RETRYING executions can be retried (current: {ex.status.value})")
        if ex.attempt_count >= ex.max_attempts:
            raise RuntimeError(f"Max retry attempts ({ex.max_attempts}) reached")

        steps = (
            await db.execute(
                select(WorkflowExecutionStep)
                .where(WorkflowExecutionStep.execution_id == ex.id)
                .order_by(WorkflowExecutionStep.step_index)
            )
        ).scalars().all()
        resume_step = 0
        for st in steps:
            if st.status == "SUCCEEDED":
                resume_step = st.step_index + 1
            else:
                resume_step = st.step_index
                break

        wf = (await db.execute(select(WorkflowDefinition).where(WorkflowDefinition.id == ex.workflow_id))).scalar_one_or_none()
        return await self.execute_workflow(
            db=db,
            workflow=wf,
            trigger_type=ex.trigger_type,
            payload=json.loads(ex.input_json or "{}"),
            start_from_step=resume_step,
            existing_execution=ex,
        )

    async def recover_stale_executions(self, db: AsyncSession, stale_minutes: int = 5) -> int:
        """Releases abandoned RUNNING locks left behind by process restarts/crashes."""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=stale_minutes)
        stale_rows = (
            await db.execute(
                select(WorkflowExecution).where(WorkflowExecution.status == WorkflowExecutionStatus.RUNNING)
            )
        ).scalars().all()
        recovered = 0
        for ex in stale_rows:
            started = ex.started_at
            if started is not None and started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            if started is None or started <= cutoff:
                ex.lock_token = None
                ex.status = (
                    WorkflowExecutionStatus.FAILED
                    if ex.attempt_count >= ex.max_attempts
                    else WorkflowExecutionStatus.RETRYING
                )
                ex.error_message = "Recovered after worker interruption/restart"
                recovered += 1
        if recovered:
            await db.commit()
        return recovered

    async def run_due_scheduled_workflows(self, db: AsyncSession) -> List[WorkflowExecution]:
        """
        Claims and executes due daily/weekly/scheduled workflows atomically using optimistic DB CAS
        so concurrent workers cannot execute the same scheduled slot twice.
        """
        await self.ensure_default_workflows(db)
        now = datetime.now(timezone.utc)
        candidates = (
            await db.execute(
                select(WorkflowDefinition).where(
                    WorkflowDefinition.trigger_type.in_(["daily_schedule", "weekly_schedule", "scheduled_time"]),
                    WorkflowDefinition.is_active == True,
                    WorkflowDefinition.is_paused == False,
                )
            )
        ).scalars().all()

        executed: List[WorkflowExecution] = []
        for wf in candidates:
            due_at = wf.next_run_at
            if due_at is not None and due_at.tzinfo is None:
                due_at = due_at.replace(tzinfo=timezone.utc)
            if due_at is None or due_at > now:
                continue

            prev_last_run = wf.last_run_at
            next_dt = compute_next_run_at(wf.trigger_type, wf.schedule_cron, base_dt=now)
            cas_stmt = (
                update(WorkflowDefinition)
                .where(
                    WorkflowDefinition.id == wf.id,
                    WorkflowDefinition.next_run_at == wf.next_run_at,
                )
                .values(last_run_at=now, next_run_at=next_dt)
            )
            cas_res = await db.execute(cas_stmt)
            await db.commit()
            if cas_res.rowcount != 1:
                continue

            await db.refresh(wf)
            slot_key = f"{wf.slug}:sched:{due_at.strftime('%Y%m%d%H%M')}"
            ex = await self.execute_workflow(
                db=db,
                workflow=wf,
                trigger_type=wf.trigger_type,
                payload={"scheduled_slot": due_at.isoformat(), "previous_run_at": prev_last_run.isoformat() if prev_last_run else None},
                idempotency_key=slot_key,
            )
            executed.append(ex)
        return executed


automation_engine = AutomationEngine()
