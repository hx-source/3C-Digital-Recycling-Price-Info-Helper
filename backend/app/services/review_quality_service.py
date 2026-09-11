from __future__ import annotations

import math
import random
from datetime import datetime

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.models.entities import ImportBatch, QuoteCandidate, ReviewAuditLog, ReviewSample, ReviewSampleStatus, ReviewStatus
from app.schemas.quotes import ReviewQualityStatsResponse, ReviewSampleQueueResponse
from app.services.audit_service import (
    AUTO_APPROVE,
    HUMAN,
    REVOKE_AUTO_APPROVE,
    SAMPLE_FAILED,
    SAMPLE_PASSED,
    SAMPLE_SELECTED,
    SYSTEM,
    add_audit_log,
    candidate_snapshot,
)
from app.services.review_agent_service import AUTO_APPROVAL_NOTE_PREFIX, ReviewBatchNotFoundError, ReviewDiagnosisApplyError, revoke_auto_approval


def _batch(db: Session, batch_id: int) -> ImportBatch:
    batch = db.get(ImportBatch, batch_id)
    if not batch:
        raise ReviewBatchNotFoundError("导入批次不存在")
    return batch


def create_review_sample(db: Session, batch_id: int, requested_count: int | None) -> ReviewSampleQueueResponse:
    batch = _batch(db, batch_id)
    already_sampled = set(db.scalars(select(ReviewSample.candidate_id).where(ReviewSample.batch_id == batch_id)))
    eligible = [
        candidate for candidate in batch.candidates
        if candidate.review_status == ReviewStatus.APPROVED
        and (candidate.review_note or "").startswith(AUTO_APPROVAL_NOTE_PREFIX)
        and candidate.id not in already_sampled
    ]
    default_count = min(30, max(1, math.ceil(len(eligible) * 0.1))) if eligible else 0
    count = min(requested_count or default_count, len(eligible))
    selected = random.SystemRandom().sample(eligible, count) if count else []
    for candidate in selected:
        sample = ReviewSample(batch_id=batch_id, candidate_id=candidate.id, status=ReviewSampleStatus.PENDING)
        db.add(sample)
        add_audit_log(
            db,
            action_type=SAMPLE_SELECTED,
            operator_type=SYSTEM,
            before_data=None,
            after_data=candidate_snapshot(candidate),
            batch_id=batch_id,
            candidate_id=candidate.id,
            reason="该记录被随机选入自动审批质量抽查",
        )
    db.commit()
    items = list(db.scalars(select(ReviewSample).where(ReviewSample.batch_id == batch_id).order_by(ReviewSample.status, ReviewSample.sampled_at.desc())))
    return ReviewSampleQueueResponse(
        batch_id=batch_id,
        requested_count=requested_count or default_count,
        created_count=len(selected),
        eligible_count=len(eligible),
        items=items,
    )


def list_review_samples(db: Session, batch_id: int) -> list[ReviewSample]:
    _batch(db, batch_id)
    return list(db.scalars(select(ReviewSample).where(ReviewSample.batch_id == batch_id).order_by(ReviewSample.status, ReviewSample.sampled_at.desc())))


def decide_review_sample(db: Session, sample_id: int, decision: str, note: str | None) -> ReviewSample:
    sample = db.get(ReviewSample, sample_id)
    if not sample:
        raise ReviewDiagnosisApplyError("抽查记录不存在")
    if sample.status != ReviewSampleStatus.PENDING:
        raise ReviewDiagnosisApplyError("这条抽查已经完成，不能重复提交")
    candidate = sample.candidate
    before_data = candidate_snapshot(candidate)
    if decision == "failed":
        revoke_auto_approval(db, candidate.id)
        db.refresh(sample)
        candidate = sample.candidate
        sample.status = ReviewSampleStatus.FAILED
        action = SAMPLE_FAILED
        reason = (note or "人工抽查发现问题，已撤销自动通过并退回待复核").strip()
    else:
        sample.status = ReviewSampleStatus.PASSED
        action = SAMPLE_PASSED
        reason = (note or "人工抽查确认自动审批结果正确").strip()
    sample.note = reason[:500]
    sample.reviewed_at = datetime.now()
    add_audit_log(
        db,
        action_type=action,
        operator_type=HUMAN,
        before_data=before_data,
        after_data=candidate_snapshot(candidate),
        batch_id=sample.batch_id,
        candidate_id=candidate.id,
        reason=sample.note,
    )
    db.commit()
    db.refresh(sample)
    return sample


def review_quality_stats(db: Session, batch_id: int) -> ReviewQualityStatsResponse:
    batch = _batch(db, batch_id)
    auto_approved_total = db.scalar(select(func.count(distinct(ReviewAuditLog.candidate_id))).where(
        ReviewAuditLog.batch_id == batch_id, ReviewAuditLog.action_type == AUTO_APPROVE
    )) or 0
    revoked_total = db.scalar(select(func.count(distinct(ReviewAuditLog.candidate_id))).where(
        ReviewAuditLog.batch_id == batch_id, ReviewAuditLog.action_type == REVOKE_AUTO_APPROVE
    )) or 0
    counts = dict(db.execute(select(ReviewSample.status, func.count(ReviewSample.id)).where(
        ReviewSample.batch_id == batch_id
    ).group_by(ReviewSample.status)).all())
    pending = counts.get(ReviewSampleStatus.PENDING, 0)
    passed = counts.get(ReviewSampleStatus.PASSED, 0)
    failed = counts.get(ReviewSampleStatus.FAILED, 0)
    sampled = pending + passed + failed
    verified = passed + failed
    current_auto = sum(
        candidate.review_status == ReviewStatus.APPROVED
        and (candidate.review_note or "").startswith(AUTO_APPROVAL_NOTE_PREFIX)
        for candidate in batch.candidates
    )
    return ReviewQualityStatsResponse(
        batch_id=batch_id,
        auto_approved_total=auto_approved_total,
        currently_auto_approved=current_auto,
        sampled_total=sampled,
        sampled_pending=pending,
        sampled_passed=passed,
        sampled_failed=failed,
        revoked_total=revoked_total,
        sample_coverage_percent=round(sampled / auto_approved_total * 100, 1) if auto_approved_total else 0,
        verified_accuracy_percent=round(passed / verified * 100, 1) if verified else None,
    )
