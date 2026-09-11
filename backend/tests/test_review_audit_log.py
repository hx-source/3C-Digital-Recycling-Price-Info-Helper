from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.imports import list_batch_audit_logs, list_candidate_audit_logs, patch_candidate
from app.core.database import Base
from app.models.entities import BatchStatus, ImportBatch, ReviewStatus, SourceType
from app.schemas.quotes import CandidateUpdate
from app.services.audit_service import MANUAL_EDIT
from app.services.import_service import candidate_from_parsed
from app.services.parser import parse_text_line


def test_manual_edit_creates_queryable_before_after_audit_log() -> None:
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
        candidate = candidate_from_parsed(
            batch.id,
            parse_text_line(
                "P90 12+256 黑1800",
                sheet_name="华为系列",
                quote_date=quote_date,
                cell_address="B3",
            )[0],
        )
        db.add(candidate)
        db.commit()

        updated = patch_candidate(
            candidate.id,
            CandidateUpdate(
                price=1850,
                review_status=ReviewStatus.APPROVED,
                review_note="对照表格确认价格",
            ),
            db,
        )

        assert str(updated.price) == "1850.00"
        candidate_logs = list_candidate_audit_logs(candidate.id, db, limit=100)
        batch_logs = list_batch_audit_logs(batch.id, db, action_type=MANUAL_EDIT, limit=100)
        assert len(candidate_logs) == 1
        assert len(batch_logs) == 1
        log = candidate_logs[0]
        assert log.action_type == MANUAL_EDIT
        assert log.before_data["price"] == "1800.00"
        assert log.after_data["price"] == "1850.00"
        assert set(log.changed_fields) >= {"price", "review_status", "review_note"}
