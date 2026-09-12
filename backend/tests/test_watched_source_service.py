from datetime import date

from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.entities import BatchStatus, ImportBatch
from app.services.watched_source_service import import_watched_workbook


def test_watched_workbook_creates_review_batch_and_skips_duplicate(tmp_path, monkeypatch) -> None:
    workbook_path = tmp_path / "思物通讯每日报价表.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "VIVO"
    sheet["A1"] = "郑州思物通讯—9.11收货行情"
    sheet["A2"] = "X200s 12+256 黑3460白3460"
    workbook.save(workbook_path)
    monkeypatch.setattr("app.services.watched_source_service.settings.upload_dir", tmp_path)

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        first = import_watched_workbook(db, workbook_path)
        second = import_watched_workbook(db, workbook_path)
        batch = db.get(ImportBatch, first["batch_id"])

        assert first["status"] == "imported"
        assert first["total_candidates"] == 2
        assert batch is not None and batch.status == BatchStatus.REVIEW
        assert batch.quote_date == date(2026, 9, 11)
        assert second["status"] == "duplicate"
        assert second["batch_id"] == first["batch_id"]
