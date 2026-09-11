from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.entities import BatchStatus, ImportBatch, MarketMonitorRun, MonitorRunStatus, PriceQuote, PriceStatus, SourceType
from app.services.market_monitor_service import analyze_monitor_run


def test_monitor_detects_large_price_change_without_model_dependency(monkeypatch) -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(
        "app.services.market_monitor_service._model_summary",
        lambda run, findings, fallback: (fallback, False),
    )
    with Session(engine) as db:
        batch = ImportBatch(
            source_type=SourceType.EXCEL, source_name="测试来源", filename="test.xlsx",
            stored_path="test.xlsx", file_sha256="f" * 64, status=BatchStatus.COMMITTED,
            quote_date=date(2026, 9, 10),
        )
        db.add(batch)
        db.flush()
        db.add_all([
            PriceQuote(batch_id=batch.id, candidate_id=1, source_name="测试来源", quote_date=date(2026, 9, 9), category="手机", brand="红米", model="K80", model_normalized="K80", storage="12+256", color="黑", model_key="redmi-k80-12-256-black", price_status=PriceStatus.QUOTED, price=Decimal("2000")),
            PriceQuote(batch_id=batch.id, candidate_id=2, source_name="测试来源", quote_date=date(2026, 9, 10), category="手机", brand="红米", model="K80", model_normalized="K80", storage="12+256", color="黑", model_key="redmi-k80-12-256-black", price_status=PriceStatus.QUOTED, price=Decimal("3100")),
        ])
        run = MarketMonitorRun(id="run-id", trigger_type="manual", status=MonitorRunStatus.QUEUED)
        db.add(run)
        db.commit()

        result = analyze_monitor_run(db, run)

        assert result.status == MonitorRunStatus.COMPLETED
        assert result.scanned_quotes == 1
        assert result.danger_count == 1
        assert any(item.finding_type == "价格异常" for item in result.findings)
        assert result.generated_by_model is False
