from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.entities import (
    BatchStatus, ImportBatch, MarketMonitorFinding, PriceQuote, PriceStatus,
    QuoteCandidate, ReviewAuditLog, ReviewStatus, SourceType,
)
from app.services.market_remediation_service import apply_finding_price, diagnose_finding, dismiss_finding


def _candidate(batch_id: int, quote_date: date, price: str, raw_text: str) -> QuoteCandidate:
    return QuoteCandidate(
        batch_id=batch_id, sheet_name="红米", cell_address="A2", raw_text=raw_text,
        quote_date=quote_date, category="手机", brand="红米", model="K80",
        model_normalized="K80", storage="12+256", color="黑",
        price_status=PriceStatus.QUOTED, price=Decimal(price), confidence=0.95,
        review_status=ReviewStatus.APPROVED,
    )


def test_extreme_price_diagnosis_can_be_confirmed_and_audited(monkeypatch) -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(
        "app.services.market_remediation_service._model_diagnosis",
        lambda finding, evidence, fallback: (fallback[0], fallback[1], False),
    )
    with Session(engine) as db:
        batch = ImportBatch(
            source_type=SourceType.EXCEL, source_name="测试来源", filename="test.xlsx",
            stored_path="test.xlsx", file_sha256="a" * 64, status=BatchStatus.COMMITTED,
            quote_date=date(2026, 9, 10),
        )
        db.add(batch)
        db.flush()
        previous_candidate = _candidate(batch.id, date(2026, 9, 9), "4600", "K80 12+256 黑4600")
        current_candidate = _candidate(batch.id, date(2026, 9, 10), "46", "K80 12+256 黑46")
        db.add_all([previous_candidate, current_candidate])
        db.flush()
        previous = PriceQuote(
            batch_id=batch.id, candidate_id=previous_candidate.id, source_name="测试来源",
            quote_date=previous_candidate.quote_date, category="手机", brand="红米", model="K80",
            model_normalized="K80", storage="12+256", color="黑", model_key="k80-key",
            price_status=PriceStatus.QUOTED, price=Decimal("4600"),
        )
        current = PriceQuote(
            batch_id=batch.id, candidate_id=current_candidate.id, source_name="测试来源",
            quote_date=current_candidate.quote_date, category="手机", brand="红米", model="K80",
            model_normalized="K80", storage="12+256", color="黑", model_key="k80-key",
            price_status=PriceStatus.QUOTED, price=Decimal("46"),
        )
        db.add_all([previous, current])
        db.flush()
        finding = MarketMonitorFinding(
            run_id="run", finding_type="价格异常", severity="danger", brand="红米", model="K80",
            title="价格异常", detail="4600 → 46", evidence={}, quote_id=current.id,
        )
        db.add(finding)
        db.commit()

        diagnosed = diagnose_finding(db, finding.id)
        assert diagnosed.handling_status == "diagnosed"
        assert diagnosed.proposed_price == Decimal("4600")
        assert diagnosed.diagnosis_confidence == 0.94
        assert diagnosed.evidence["source_position"] == "A2"

        resolved = apply_finding_price(db, finding.id, Decimal("4600"), None, "核对原表后确认")
        assert resolved.handling_status == "resolved"
        assert current.price == Decimal("4600")
        assert current_candidate.price == Decimal("4600")
        log = db.scalar(select(ReviewAuditLog).where(ReviewAuditLog.candidate_id == current_candidate.id))
        assert log is not None
        assert log.action_type == "monitor_remediation_apply"
        assert "price" in log.changed_fields


def test_structural_finding_can_be_diagnosed_then_dismissed(monkeypatch) -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(
        "app.services.market_remediation_service._model_diagnosis",
        lambda finding, evidence, fallback: (fallback[0], fallback[1], False),
    )
    with Session(engine) as db:
        finding = MarketMonitorFinding(
            run_id="run", finding_type="型号消失", severity="warning",
            title="型号消失", detail="上一期规格未出现", evidence={"count": "20"},
        )
        db.add(finding)
        db.commit()
        diagnosed = diagnose_finding(db, finding.id)
        assert diagnosed.proposed_price is None
        dismissed = dismiss_finding(db, finding.id, "确认是缺货")
        assert dismissed.handling_status == "dismissed"


def test_wildcard_price_is_restored_to_masked_instead_of_inventing_price(monkeypatch) -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(
        "app.services.market_remediation_service._model_diagnosis",
        lambda finding, evidence, fallback: (fallback[0], fallback[1], False),
    )
    with Session(engine) as db:
        batch = ImportBatch(source_type=SourceType.EXCEL, source_name="测试", filename="x.xlsx", stored_path="x.xlsx", file_sha256="b" * 64, status=BatchStatus.COMMITTED, quote_date=date(2026, 9, 10))
        db.add(batch)
        db.flush()
        candidate = _candidate(batch.id, date(2026, 9, 10), "46", "Mate70Pro+ 16+512 青46xx")
        db.add(candidate)
        db.flush()
        quote = PriceQuote(batch_id=batch.id, candidate_id=candidate.id, source_name="测试", quote_date=candidate.quote_date, category="手机", brand="华为", model="Mate70Pro+", model_normalized="Mate70Pro+", storage="16+512", color="青", model_key="mate70-key", price_status=PriceStatus.QUOTED, price=Decimal("46"))
        db.add(quote)
        db.flush()
        finding = MarketMonitorFinding(run_id="run", finding_type="价格异常", severity="danger", title="价格异常", detail="异常", evidence={}, quote_id=quote.id)
        db.add(finding)
        db.commit()
        diagnosed = diagnose_finding(db, finding.id)
        assert diagnosed.proposed_price is None
        assert diagnosed.proposed_price_status == "masked"
        apply_finding_price(db, finding.id, None, "masked", "原文含通配数字")
        assert quote.price_status == PriceStatus.MASKED
        assert quote.price is None
