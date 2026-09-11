from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.entities import BatchStatus, ImportBatch, PriceQuote, ReviewAuditLog, ReviewStatus, SourceType
from app.services.audit_service import AGENT_SUGGESTION_APPLY, AUTO_APPROVE, REVOKE_AUTO_APPROVE
from app.schemas.quotes import ReviewBatchApproveSafeRequest, ReviewDiagnosisApplyRequest
from app.services.import_service import candidate_from_parsed
from app.services.parser import parse_text_line
from app.services.review_agent_service import (
    ReviewDiagnosisConflictError,
    _collect_diagnosis,
    _model_output_is_safe,
    _run_review_tool_agent,
    apply_review_diagnosis,
    approve_safe_review_batch,
    diagnose_review_batch,
    revoke_auto_approval,
)


def _batch(db: Session, *, status: BatchStatus, quote_date: date, token: str) -> ImportBatch:
    batch = ImportBatch(
        source_type=SourceType.IMAGE,
        source_name="测试来源",
        filename=f"{token}.png",
        stored_path=f"{token}.png",
        file_sha256=token * 64,
        status=status,
        quote_date=quote_date,
    )
    db.add(batch)
    db.flush()
    return batch


def test_review_diagnosis_collects_evidence_and_applies_only_confirmed_suggestion() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        previous_date = date(2026, 8, 20)
        previous_batch = _batch(db, status=BatchStatus.COMMITTED, quote_date=previous_date, token="a")
        previous_candidate = candidate_from_parsed(
            previous_batch.id,
            parse_text_line(
                "P90Pro 12+256 黑1800",
                sheet_name="华为系列",
                quote_date=previous_date,
                cell_address="image:r5:c2",
            )[0],
        )
        db.add(previous_candidate)
        db.flush()
        db.add(
            PriceQuote(
                batch_id=previous_batch.id,
                candidate_id=previous_candidate.id,
                source_name=previous_batch.source_name,
                quote_date=previous_date,
                category=previous_candidate.category,
                brand=previous_candidate.brand,
                model=previous_candidate.model,
                model_normalized=previous_candidate.model_normalized,
                storage=previous_candidate.storage,
                color=previous_candidate.color,
                variant=previous_candidate.variant,
                model_key="huawei|p90pro|12+256|black",
                price_status=previous_candidate.price_status,
                price=previous_candidate.price,
            )
        )

        current_date = date(2026, 8, 21)
        current_batch = _batch(db, status=BatchStatus.REVIEW, quote_date=current_date, token="b")
        parsed = parse_text_line(
            "P90Pro 12+256 黑2600白2650橙2660",
            sheet_name="华为系列",
            quote_date=current_date,
            cell_address="image:r5:c2",
            source_line=5,
        )[0]
        first = candidate_from_parsed(current_batch.id, parsed)
        duplicate = candidate_from_parsed(current_batch.id, parsed)
        duplicate.confidence = 0.68
        db.add_all([first, duplicate])
        db.commit()

        diagnosis = _collect_diagnosis(db, duplicate.id)

        assert diagnosis.severity == "danger"
        assert set(diagnosis.issue_types) >= {
            "低置信度",
            "重复报价",
            "价格异常波动",
            "来源行拆分不一致",
        }
        assert any(item.field == "review_status" for item in diagnosis.proposed_changes)

        result = apply_review_diagnosis(
            db,
            duplicate.id,
            ReviewDiagnosisApplyRequest(
                candidate_signature=diagnosis.signature,
                decision="apply_suggestions",
                fields=["review_status"],
            ),
        )

        assert result.candidate.review_status.value == "rejected"
        assert result.candidate.confidence == 0.68
        assert result.candidate.review_note.startswith("[智能诊断确认]")
        assert result.applied_fields == ["复核状态"]
        assert "重复报价" in result.remaining_issue_types
        assert "不会进入正式报价" in result.verification_summary
        log = db.scalar(select(ReviewAuditLog).order_by(ReviewAuditLog.id.desc()))
        assert log is not None
        assert log.action_type == AGENT_SUGGESTION_APPLY
        assert log.before_data["review_status"] == "pending"
        assert log.after_data["review_status"] == "rejected"
        assert set(log.changed_fields) >= {"review_status", "review_note"}


def test_review_agent_rejects_unsupported_model_certainty_and_new_numbers() -> None:
    facts = {"evidence": ["原始识别置信度为58%"], "rule_recommendations": ["请人工核对"]}

    assert _model_output_is_safe("置信度为58%，需要人工核对。", ["请人工核对"], facts)
    assert not _model_output_is_safe("型号识别准确。", ["请人工核对"], facts)
    assert not _model_output_is_safe("价格可能是1800元。", ["请人工核对"], facts)


def test_batch_review_scans_all_and_only_approves_pending_safe_candidates() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        quote_date = date(2026, 8, 21)
        batch = _batch(db, status=BatchStatus.REVIEW, quote_date=quote_date, token="c")
        safe = candidate_from_parsed(
            batch.id,
            parse_text_line(
                "P90 12+256 黑1800",
                sheet_name="华为系列",
                quote_date=quote_date,
                cell_address="B3",
            )[0],
        )
        risky = candidate_from_parsed(
            batch.id,
            parse_text_line(
                "P90Pro 12+256 黑2600",
                sheet_name="华为系列",
                quote_date=quote_date,
                cell_address="B4",
            )[0],
        )
        safe.confidence = 0.92
        risky.confidence = 0.61
        db.add_all([safe, risky])
        db.commit()

        diagnosis = diagnose_review_batch(db, batch.id)

        assert diagnosis.scanned_count == 2
        assert diagnosis.safe_count == 1
        assert diagnosis.pending_safe_count == 1
        assert diagnosis.warning_count == 1
        assert diagnosis.danger_count == 0
        assert diagnosis.issue_counts == {"低置信度": 1}
        assert diagnosis.risks[0].candidate.id == risky.id

        result = approve_safe_review_batch(
            db,
            batch.id,
            ReviewBatchApproveSafeRequest(batch_signature=diagnosis.batch_signature),
        )

        db.refresh(safe)
        db.refresh(risky)
        assert result.approved_count == 1
        assert result.remaining_pending == 1
        assert safe.review_status == ReviewStatus.APPROVED
        assert safe.review_note.startswith("[智能批量审核]")
        assert safe.confidence == 0.92
        assert risky.review_status == ReviewStatus.PENDING
        auto_log = db.scalar(
            select(ReviewAuditLog).where(ReviewAuditLog.action_type == AUTO_APPROVE)
        )
        assert auto_log is not None
        assert auto_log.agent_run_id == result.agent_run_id
        assert auto_log.before_data["review_status"] == "pending"
        assert auto_log.after_data["review_status"] == "approved"

        rescanned = diagnose_review_batch(db, batch.id)
        assert rescanned.auto_approved_count == 1
        assert rescanned.pending_safe_count == 0

        revoked = revoke_auto_approval(db, safe.id)
        assert revoked.review_status == ReviewStatus.PENDING
        assert revoked.review_note.startswith("[已撤销自动审核]")
        revoke_log = db.scalar(
            select(ReviewAuditLog).where(ReviewAuditLog.action_type == REVOKE_AUTO_APPROVE)
        )
        assert revoke_log is not None
        assert revoke_log.before_data["review_status"] == "approved"
        assert revoke_log.after_data["review_status"] == "pending"

        rescanned = diagnose_review_batch(db, batch.id)
        assert rescanned.auto_approved_count == 0
        assert rescanned.pending_safe_count == 1

        with pytest.raises(ReviewDiagnosisConflictError):
            approve_safe_review_batch(
                db,
                batch.id,
                ReviewBatchApproveSafeRequest(batch_signature=diagnosis.batch_signature),
            )


def test_batch_review_keeps_medium_confidence_candidate_for_human_review() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        quote_date = date(2026, 8, 21)
        batch = _batch(db, status=BatchStatus.REVIEW, quote_date=quote_date, token="e")
        candidate = candidate_from_parsed(
            batch.id,
            parse_text_line(
                "P90 12+256 黑1800",
                sheet_name="华为系列",
                quote_date=quote_date,
                cell_address="B3",
            )[0],
        )
        candidate.confidence = 0.88
        db.add(candidate)
        db.commit()

        diagnosis = diagnose_review_batch(db, batch.id)

        assert diagnosis.pending_safe_count == 0
        assert diagnosis.warning_count == 1
        assert diagnosis.risks[0].issue_types == ["置信度未达自动通过标准"]
        assert "对照来源" in diagnosis.risks[0].summary


def test_review_agent_uses_model_tools_and_fills_mandatory_safety_checks(monkeypatch) -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    monkeypatch.setattr(
        "app.services.review_agent_service._ollama_chat",
        lambda _payload: {
            "message": {
                "content": '{"checks":["inspect_source","compare_history"],"reason":"先核对来源和价格"}'
            }
        },
    )

    with Session(engine) as db:
        quote_date = date(2026, 8, 21)
        batch = _batch(db, status=BatchStatus.REVIEW, quote_date=quote_date, token="d")
        candidate = candidate_from_parsed(
            batch.id,
            parse_text_line(
                "P90 12+256 黑1800",
                sheet_name="华为系列",
                quote_date=quote_date,
                cell_address="B3",
            )[0],
        )
        candidate.confidence = 0.92
        db.add(candidate)
        db.commit()

        tools, steps, model_selected = _run_review_tool_agent(db, candidate)

        assert model_selected is True
        assert tools == ["inspect_source", "compare_history", "check_duplicates", "check_source_structure"]
        assert steps[0].phase == "planning"
        assert steps[0].status == "completed"
        assert [step.tool for step in steps if step.status == "fallback"] == [
            "check_duplicates",
            "check_source_structure",
        ]
