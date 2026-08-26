from datetime import date
from decimal import Decimal

from app.models.entities import PriceQuote, PriceStatus
from app.services.excel_precheck import inspect_excel_candidates
from app.services.normalizer import model_key
from app.services.parser import parse_text_line


QUOTE_DATE = date(2026, 8, 22)


def test_excel_precheck_flags_duplicates_missing_prices_and_large_changes() -> None:
    normal = parse_text_line(
        "X200s 12+256 黑3460",
        sheet_name="VIVO",
        quote_date=QUOTE_DATE,
    )[0]
    duplicate = parse_text_line(
        "X200s 12+256 黑3460",
        sheet_name="VIVO",
        quote_date=QUOTE_DATE,
    )[0]
    missing_price = parse_text_line(
        "X300 12+256",
        sheet_name="VIVO",
        quote_date=QUOTE_DATE,
    )[0]
    historical = PriceQuote(
        id=1,
        batch_id=1,
        candidate_id=1,
        source_name="历史来源",
        quote_date=date(2026, 8, 20),
        category="手机",
        brand="vivo",
        model="X200s",
        model_normalized="X200s",
        storage="12+256",
        color="黑",
        variant=None,
        model_key=model_key("vivo", "X200s", "12+256", "黑", None),
        price_status=PriceStatus.QUOTED,
        price=Decimal("2800"),
    )

    report = inspect_excel_candidates([normal, duplicate, missing_price], [historical])

    assert report.duplicate_candidates == 2
    assert report.no_quote_candidates == 1
    assert report.abnormal_price_candidates == 2
    assert report.normal_items == []
    assert any("重复报价" in issue["reasons"] for issue in report.issues)
    assert any("暂无报价" in issue["reasons"] for issue in report.issues)
    assert any("价格波动≥500" in issue["reasons"] for issue in report.issues)
    assert len(report.records) == 3
    duplicate_record = next(record for record in report.records if "重复报价" in record["reasons"])
    assert duplicate_record["raw_text"] == "X200s 12+256 黑3460"
    assert "当前表中有 2 条相同型号规格" in (duplicate_record["duplicate_detail"] or "")
