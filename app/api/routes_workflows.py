import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_admin, verify_cron_or_admin
from app.models.entities import (
    AutomationApproval,
    WorkflowDefinition,
    WorkflowExecution,
    WorkflowExecutionStatus,
    WorkflowExecutionStep,
)
from app.services.automation_engine import SUPPORTED_TRIGGERS, automation_engine, compute_next_run_at

router = APIRouter(
    prefix="/workflows",
    tags=["Automation & Workflow Engine"],
)


class WorkflowCreatePayload(BaseModel):
    slug: str = Field(..., min_length=2, max_length=100)
    name: str = Field(..., min_length=2, max_length=200)
    description: Optional[str] = None
    trigger_type: str = Field(..., max_length=60)
    conditions: List[Dict[str, Any]] = Field(default_factory=list)
    actions: List[Dict[str, Any]] = Field(default_factory=list)
    approval_required: bool = False
    schedule_cron: Optional[str] = None


class WorkflowTriggerPayload(BaseModel):
    payload: Dict[str, Any] = Field(default_factory=dict)
    idempotency_key: Optional[str] = None


class ApprovalDecisionPayload(BaseModel):
    notes: Optional[str] = None


def _serialize_workflow(wf: WorkflowDefinition) -> Dict[str, Any]:
    return {
        "id": wf.id,
        "slug": wf.slug,
        "name": wf.name,
        "description": wf.description,
        "trigger_type": wf.trigger_type,
        "conditions": json.loads(wf.conditions_json or "[]"),
        "actions": json.loads(wf.actions_json or "[]"),
        "retry_policy": json.loads(wf.retry_policy_json or "{}"),
        "approval_required": wf.approval_required,
        "is_active": wf.is_active,
        "is_paused": wf.is_paused,
        "schedule_cron": wf.schedule_cron,
        "last_run_at": wf.last_run_at.isoformat() if wf.last_run_at else None,
        "next_run_at": wf.next_run_at.isoformat() if wf.next_run_at else None,
        "created_at": wf.created_at.isoformat() if wf.created_at else None,
    }


def _serialize_execution(ex: WorkflowExecution, wf_name: Optional[str] = None) -> Dict[str, Any]:
    return {
        "id": ex.id,
        "execution_uid": ex.execution_uid,
        "workflow_id": ex.workflow_id,
        "workflow_name": wf_name,
        "trigger_type": ex.trigger_type,
        "status": ex.status.value if hasattr(ex.status, "value") else str(ex.status),
        "idempotency_key": ex.idempotency_key,
        "input": json.loads(ex.input_json or "{}"),
        "output": json.loads(ex.output_json or "{}"),
        "error_message": ex.error_message,
        "attempt_count": ex.attempt_count,
        "max_attempts": ex.max_attempts,
        "started_at": ex.started_at.isoformat() if ex.started_at else None,
        "completed_at": ex.completed_at.isoformat() if ex.completed_at else None,
        "created_at": ex.created_at.isoformat() if ex.created_at else None,
    }


@router.get("/meta/triggers", dependencies=[Depends(require_admin)])
async def list_supported_triggers():
    return {
        "triggers": SUPPORTED_TRIGGERS,
        "actions": [
            {"type": "score_lead", "label": "Score & Segment Lead"},
            {"type": "create_followup_task", "label": "Schedule Follow-Up Task"},
            {"type": "prepare_whatsapp_draft", "label": "Prepare WhatsApp Draft"},
            {"type": "send_whatsapp_template", "label": "Send via WhatsApp Cloud API"},
            {"type": "generate_ai_content", "label": "Generate AI Content"},
            {"type": "sync_and_autopilot_drive", "label": "Run Drive Auto-Pilot"},
            {"type": "run_gbp_publish_cycle", "label": "Run GBP Publishing Cycle"},
            {"type": "sync_reviews", "label": "Sync Google Reviews"},
            {"type": "run_seo_competitor_check", "label": "Check SEO & Competitors"},
            {"type": "require_approval", "label": "Require Human Approval"},
            {"type": "delay_wait", "label": "Wait / Delay"},
            {"type": "notify_admin", "label": "Notify Admin & Audit"},
        ],
    }


@router.get("", dependencies=[Depends(require_admin)])
async def list_workflows(db: AsyncSession = Depends(get_db)):
    await automation_engine.ensure_default_workflows(db)
    rows = (await db.execute(select(WorkflowDefinition).order_by(WorkflowDefinition.id))).scalars().all()
    return [_serialize_workflow(w) for w in rows]


@router.post("", dependencies=[Depends(require_admin)])
async def create_workflow(body: WorkflowCreatePayload, db: AsyncSession = Depends(get_db)):
    if body.trigger_type not in SUPPORTED_TRIGGERS:
        raise HTTPException(status_code=400, detail=f"Unsupported trigger_type '{body.trigger_type}'")
    clean_slug = body.slug.strip().lower()
    existing = (
        await db.execute(select(WorkflowDefinition).where(WorkflowDefinition.slug == clean_slug))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail=f"Workflow slug '{clean_slug}' already exists")
    wf = WorkflowDefinition(
        slug=clean_slug,
        name=body.name.strip(),
        description=body.description,
        trigger_type=body.trigger_type,
        conditions_json=json.dumps(body.conditions),
        actions_json=json.dumps(body.actions),
        approval_required=body.approval_required,
        schedule_cron=body.schedule_cron,
        next_run_at=compute_next_run_at(body.trigger_type, body.schedule_cron),
        is_active=True,
        is_paused=False,
    )
    db.add(wf)
    await db.commit()
    await db.refresh(wf)
    return _serialize_workflow(wf)


@router.post("/{workflow_id}/run", dependencies=[Depends(require_admin)])
async def run_workflow_now(
    workflow_id: int,
    body: Optional[WorkflowTriggerPayload] = None,
    db: AsyncSession = Depends(get_db),
):
    wf = (await db.execute(select(WorkflowDefinition).where(WorkflowDefinition.id == workflow_id))).scalar_one_or_none()
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if wf.is_paused:
        raise HTTPException(status_code=409, detail="Workflow is paused. Resume it before running.")
    ex = await automation_engine.execute_workflow(
        db=db,
        workflow=wf,
        trigger_type="manual_execution",
        payload=(body.payload if body else {}),
        idempotency_key=(body.idempotency_key if body else None),
    )
    return _serialize_execution(ex, wf.name)


@router.post("/{workflow_id}/pause", dependencies=[Depends(require_admin)])
async def pause_workflow(workflow_id: int, db: AsyncSession = Depends(get_db)):
    wf = (await db.execute(select(WorkflowDefinition).where(WorkflowDefinition.id == workflow_id))).scalar_one_or_none()
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    wf.is_paused = True
    await db.commit()
    await db.refresh(wf)
    return _serialize_workflow(wf)


@router.post("/{workflow_id}/resume", dependencies=[Depends(require_admin)])
async def resume_workflow(workflow_id: int, db: AsyncSession = Depends(get_db)):
    wf = (await db.execute(select(WorkflowDefinition).where(WorkflowDefinition.id == workflow_id))).scalar_one_or_none()
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    wf.is_paused = False
    wf.is_active = True
    await db.commit()
    await db.refresh(wf)
    return _serialize_workflow(wf)


@router.delete("/{workflow_id}", dependencies=[Depends(require_admin)])
async def delete_workflow(workflow_id: int, db: AsyncSession = Depends(get_db)):
    wf = (await db.execute(select(WorkflowDefinition).where(WorkflowDefinition.id == workflow_id))).scalar_one_or_none()
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    await db.delete(wf)
    await db.commit()
    return {"status": "DELETED", "id": workflow_id}


@router.post("/scheduler/tick", dependencies=[Depends(verify_cron_or_admin)])
async def trigger_scheduler_tick(db: AsyncSession = Depends(get_db)):
    """Cron & background worker tick: recovers stale locks and runs all due scheduled workflows safely."""
    recovered = await automation_engine.recover_stale_executions(db)
    runs = await automation_engine.run_due_scheduled_workflows(db)
    return {
        "status": "OK",
        "recovered_stale": recovered,
        "executed_count": len(runs),
        "executions": [_serialize_execution(r) for r in runs],
    }


@router.get("/executions", dependencies=[Depends(require_admin)])
async def list_executions(limit: int = 50, db: AsyncSession = Depends(get_db)):
    wfs = {w.id: w.name for w in (await db.execute(select(WorkflowDefinition))).scalars().all()}
    rows = (
        await db.execute(select(WorkflowExecution).order_by(desc(WorkflowExecution.created_at)).limit(limit))
    ).scalars().all()
    return [_serialize_execution(ex, wfs.get(ex.workflow_id)) for ex in rows]


@router.get("/executions/{execution_id}", dependencies=[Depends(require_admin)])
async def get_execution_detail(execution_id: int, db: AsyncSession = Depends(get_db)):
    ex = (await db.execute(select(WorkflowExecution).where(WorkflowExecution.id == execution_id))).scalar_one_or_none()
    if not ex:
        raise HTTPException(status_code=404, detail="Execution not found")
    wf = (await db.execute(select(WorkflowDefinition).where(WorkflowDefinition.id == ex.workflow_id))).scalar_one_or_none()
    steps = (
        await db.execute(
            select(WorkflowExecutionStep)
            .where(WorkflowExecutionStep.execution_id == ex.id)
            .order_by(WorkflowExecutionStep.step_index)
        )
    ).scalars().all()
    return {
        **_serialize_execution(ex, wf.name if wf else None),
        "steps": [
            {
                "id": s.id,
                "step_index": s.step_index,
                "step_name": s.step_name,
                "action_type": s.action_type,
                "status": s.status,
                "input": json.loads(s.input_json or "{}"),
                "output": json.loads(s.output_json or "{}"),
                "error_message": s.error_message,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "completed_at": s.completed_at.isoformat() if s.completed_at else None,
            }
            for s in steps
        ],
    }


@router.post("/executions/{execution_id}/retry", dependencies=[Depends(require_admin)])
async def retry_execution(execution_id: int, db: AsyncSession = Depends(get_db)):
    try:
        updated = await automation_engine.retry_execution(db, execution_id)
        wf = (await db.execute(select(WorkflowDefinition).where(WorkflowDefinition.id == updated.workflow_id))).scalar_one_or_none()
        return _serialize_execution(updated, wf.name if wf else None)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/executions/{execution_id}/cancel", dependencies=[Depends(require_admin)])
async def cancel_execution(execution_id: int, db: AsyncSession = Depends(get_db)):
    ex = (await db.execute(select(WorkflowExecution).where(WorkflowExecution.id == execution_id))).scalar_one_or_none()
    if not ex:
        raise HTTPException(status_code=404, detail="Execution not found")
    ex.status = WorkflowExecutionStatus.CANCELLED
    ex.completed_at = datetime.now(timezone.utc)
    ex.lock_token = None
    await db.commit()
    await db.refresh(ex)
    return _serialize_execution(ex)


@router.get("/approvals", dependencies=[Depends(require_admin)])
async def list_approvals(status: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    stmt = select(AutomationApproval).order_by(desc(AutomationApproval.created_at))
    if status:
        stmt = stmt.where(AutomationApproval.status == status.upper())
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": a.id,
            "execution_id": a.execution_id,
            "title": a.title,
            "description": a.description,
            "payload": json.loads(a.payload_json or "{}"),
            "status": a.status,
            "reviewed_by": a.reviewed_by,
            "reviewed_at": a.reviewed_at.isoformat() if a.reviewed_at else None,
            "decision_notes": a.decision_notes,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in rows
    ]


@router.post("/approvals/{approval_id}/approve")
async def approve_workflow_step(
    approval_id: int,
    body: Optional[ApprovalDecisionPayload] = None,
    admin_user: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        ex = await automation_engine.approve_and_resume(
            db=db,
            approval_id=approval_id,
            reviewer=admin_user,
            notes=(body.notes if body else None),
        )
        return _serialize_execution(ex)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/approvals/{approval_id}/reject")
async def reject_workflow_step(
    approval_id: int,
    body: Optional[ApprovalDecisionPayload] = None,
    admin_user: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        ap = await automation_engine.reject_approval(
            db=db,
            approval_id=approval_id,
            reviewer=admin_user,
            notes=(body.notes if body else None),
        )
        return {"id": ap.id, "status": ap.status, "reviewed_by": ap.reviewed_by}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
