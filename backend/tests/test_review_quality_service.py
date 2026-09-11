from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.entities import BatchStatus, ImportBatch, ReviewSampleStatus, ReviewStatus, SourceType
from app.services.audit_service import AGENT, AUTO_APPROVE, add_audit_log, candidate_snapshot
from app.services.import_service import candidate_from_parsed
from app.services.parser import parse_text_line
from app.services.review_agent_service import AUTO_APPROVAL_NOTE_PREFIX
from app.services.review_quality_service import create_review_sample, decide_review_sample, review_quality_stats


def test_sample_decisions_update_quality_and_revoke_bad_auto_approval() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        quote_date = date(2026, 9, 10)
        batch = ImportBatch(
            source_type=SourceType.EXCEL,
            source_name="测试来源",
            filename="test.xlsx",
            stored_path="test.xlsx",
            file_sha256="f" * 64,
            status=BatchStatus.REVIEW,
            quote_date=quote_date,
        )
        db.add(batch)
        db.flush()
        for index, text in enumerate(("P90 12+256 黑1800", "P90 12+256 白1810"), start=1):
            candidate = candidate_from_parsed(
                batch.id,
                parse_text_line(text, sheet_name="华为系列", quote_date=quote_date, cell_address=f"B{index}")[0],
            )
            candidate.review_status = ReviewStatus.APPROVED
            candidate.review_note = f"{AUTO_APPROVAL_NOTE_PREFIX} 测试"
            db.add(candidate)
            db.flush()
            add_audit_log(
                db,
                action_type=AUTO_APPROVE,
                operator_type=AGENT,
                before_data=None,
                after_data=candidate_snapshot(candidate),
                batch_id=batch.id,
                candidate_id=candidate.id,
            )
        db.commit()

        queue = create_review_sample(db, batch.id, 2)
        assert queue.created_count == 2
        decide_review_sample(db, queue.items[0].id, "passed", None)
        failed = decide_review_sample(db, queue.items[1].id, "failed", "价格需要复查")

        assert failed.status == ReviewSampleStatus.FAILED
        assert failed.candidate.review_status == ReviewStatus.PENDING
        stats = review_quality_stats(db, batch.id)
        assert stats.auto_approved_total == 2
        assert stats.sampled_passed == 1
        assert stats.sampled_failed == 1
        assert stats.revoked_total == 1
        assert stats.verified_accuracy_percent == 50.0
