from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.routes.imports import (
    delete_candidate,
    delete_candidate_source_group,
    delete_import,
    get_candidate_source_group,
    reopen_import_for_review,
    replace_candidate_source_group,
    reparse_candidate_source_line,
    update_import_quote_date,
)
from app.core.database import Base
from app.models.entities import BatchStatus, ImportBatch, PriceQuote, PriceStatus, QuoteCandidate, SourceType
from app.schemas.quotes import (
    BatchQuoteDateUpdate,
    SourceGroupCandidateInput,
    SourceGroupReplaceRequest,
    SourceLineReparseRequest,
)
from app.services.import_service import candidate_from_parsed
from app.services.parser import parse_text_line


def test_excel_source_group_keeps_same_cell_addresses_on_different_sheets_separate() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    quote_date = date(2026, 8, 24)

    with Session(engine) as db:
        batch = ImportBatch(
            source_type=SourceType.EXCEL,
            source_name="测试来源",
            filename="source.xlsx",
            stored_path="source.xlsx",
            file_sha256="d" * 64,
            status=BatchStatus.REVIEW,
            quote_date=quote_date,
        )
        db.add(batch)
        db.flush()
        oppo = candidate_from_parsed(
            batch.id,
            parse_text_line("OPPOK12s 8+128 黑1260", sheet_name="OPPO", quote_date=quote_date, cell_address="B4")[0],
        )
        vivo = candidate_from_parsed(
            batch.id,
            parse_text_line("X200s 12+256 黑3460", sheet_name="VIVO", quote_date=quote_date, cell_address="B4")[0],
        )
        db.add_all([oppo, vivo])
        db.commit()

        result = get_candidate_source_group(oppo.id, db)

        assert [candidate.id for candidate in result] == [oppo.id]


def test_corrected_source_line_replaces_records_instead_of_appending() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    quote_date = date(2026, 8, 20)

    with Session(engine) as db:
        batch = ImportBatch(
            source_type=SourceType.IMAGE,
            source_name="测试来源",
            filename="source.png",
            stored_path="source.png",
            file_sha256="a" * 64,
            status=BatchStatus.REVIEW,
            quote_date=quote_date,
        )
        db.add(batch)
        db.flush()
        initial = parse_text_line(
            "P90Pro 12+256 黑4680白4750橙4700",
            sheet_name="华为系列",
            quote_date=quote_date,
            cell_address="image:r5:c2",
            source_line=5,
        )
        old_records = [candidate_from_parsed(batch.id, item) for item in initial]
        db.add_all(old_records)
        db.commit()
        result = reparse_candidate_source_line(
            old_records[0].id,
            SourceLineReparseRequest(raw_text="P90Pro 12+256 黑4680白4750橙4700粉4800"),
            db,
        )

        current = list(
            db.scalars(select(QuoteCandidate).where(QuoteCandidate.batch_id == batch.id).order_by(QuoteCandidate.id))
        )
        assert len(result) == 4
        assert len(current) == 4
        assert {item.color for item in current} == {"黑", "白", "橙", "粉"}
        assert {item.raw_text for item in current} == {"P90Pro 12+256 黑4680白4750橙4700粉4800"}
        assert batch.total_candidates == 4

        replaced = replace_candidate_source_group(
            current[0].id,
            SourceGroupReplaceRequest(
                items=[
                    SourceGroupCandidateInput(id=current[0].id),
                    SourceGroupCandidateInput(id=current[1].id),
                    SourceGroupCandidateInput(id=current[2].id),
                    SourceGroupCandidateInput(
                        brand="Other",
                        model="P90Pro",
                        storage="12+256",
                        color="绿",
                        price_status=PriceStatus.QUOTED,
                        price=4800,
                    ),
                ]
            ),
            db,
        )
        assert len(replaced) == 4
        assert {item.confidence for item in replaced} == {1.0}
        current = list(db.scalars(select(QuoteCandidate).where(QuoteCandidate.batch_id == batch.id)))
        assert {item.color for item in current} == {"黑", "白", "橙", "绿"}

        assert delete_candidate(current[0].id, db) == {"deleted": 1}
        remaining = list(db.scalars(select(QuoteCandidate).where(QuoteCandidate.batch_id == batch.id)))
        assert len(remaining) == 3

        assert delete_candidate_source_group(remaining[0].id, db) == {"deleted": 3}
        assert db.scalars(select(QuoteCandidate).where(QuoteCandidate.batch_id == batch.id)).all() == []
        assert batch.total_candidates == 0

        delete_batch = ImportBatch(
            source_type=SourceType.IMAGE,
            source_name="测试来源",
            filename="delete-source.png",
            stored_path="not-a-managed-upload.png",
            file_sha256="b" * 64,
            status=BatchStatus.REVIEW,
            quote_date=quote_date,
        )
        db.add(delete_batch)
        db.flush()
        record = candidate_from_parsed(
            delete_batch.id,
            parse_text_line("P90Pro 12+256 黑4680", sheet_name="图片自动识别", quote_date=quote_date)[0],
        )
        db.add(record)
        db.commit()

        assert delete_import(delete_batch.id, db) == {"deleted_batches": 1, "deleted_candidates": 1}
        assert db.get(ImportBatch, delete_batch.id) is None
        assert db.scalars(select(QuoteCandidate).where(QuoteCandidate.batch_id == delete_batch.id)).all() == []

        history_batch = ImportBatch(
            source_type=SourceType.IMAGE,
            source_name="测试来源",
            filename="published-source.png",
            stored_path="published-source.png",
            file_sha256="c" * 64,
            status=BatchStatus.COMMITTED,
            quote_date=quote_date,
        )
        db.add(history_batch)
        db.flush()
        history_candidate = candidate_from_parsed(
            history_batch.id,
            parse_text_line("P90Pro 12+256 黑4680", sheet_name="图片自动识别", quote_date=quote_date)[0],
        )
        db.add(history_candidate)
        db.flush()
        db.add(
            PriceQuote(
                batch_id=history_batch.id,
                candidate_id=history_candidate.id,
                source_name=history_batch.source_name,
                quote_date=quote_date,
                category=history_candidate.category,
                brand=history_candidate.brand,
                model=history_candidate.model,
                model_normalized=history_candidate.model_normalized,
                storage=history_candidate.storage,
                color=history_candidate.color,
                variant=history_candidate.variant,
                model_key="test-key",
                price_status=history_candidate.price_status,
                price=history_candidate.price,
            )
        )
        db.commit()

        corrected_date = date(2026, 8, 21)
        update_import_quote_date(history_batch.id, BatchQuoteDateUpdate(quote_date=corrected_date), db)
        assert history_batch.quote_date == corrected_date
        assert history_candidate.quote_date == corrected_date
        assert db.scalar(select(PriceQuote.quote_date).where(PriceQuote.batch_id == history_batch.id)) == corrected_date

        assert reopen_import_for_review(history_batch.id, db) == {
            "batch_id": history_batch.id,
            "removed_quotes": 1,
            "reset_candidates": 1,
        }
        assert history_batch.status == BatchStatus.REVIEW
        assert db.scalar(select(PriceQuote.id).where(PriceQuote.batch_id == history_batch.id)) is None
        assert db.get(QuoteCandidate, history_candidate.id) is not None
