import os
from datetime import date
from pathlib import Path

import pytest

from app.models.entities import PriceStatus
from app.services.excel_importer import ExcelQuoteImporter


SOURCE_VALUE = os.getenv("E2E_WORKBOOK_PATH")


def test_real_workbook_imports_candidates() -> None:
    if not SOURCE_VALUE:
        pytest.skip("设置 E2E_WORKBOOK_PATH 后运行真实工作簿测试")
    source = Path(SOURCE_VALUE).resolve()
    if not source.exists():
        pytest.skip(f"测试工作簿不存在：{source}")
    items = ExcelQuoteImporter().parse(source, date(2026, 8, 20))
    assert len(items) > 300
    assert any(item.sheet_name == "VIVO" and item.model.startswith("X200s") for item in items)
    assert any(item.price_status == PriceStatus.NO_QUOTE for item in items)
    assert any(item.price_status == PriceStatus.MASKED for item in items)
    assert all(item.raw_text != "325" for item in items)
