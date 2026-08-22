from datetime import date
from decimal import Decimal

from app.models.entities import PriceStatus
from app.services.parser import parse_text_line


QUOTE_DATE = date(2026, 8, 20)


def test_parses_multiple_color_prices() -> None:
    items = parse_text_line(
        "X200s 12+256 黑3460白3460蓝3460紫3460",
        sheet_name="VIVO",
        quote_date=QUOTE_DATE,
    )
    assert len(items) == 4
    assert {item.color for item in items} == {"黑", "白", "蓝", "紫"}
    assert all(item.price == Decimal("3460") for item in items)
    assert all(item.storage == "12+256" for item in items)


def test_preserves_no_quote() -> None:
    items = parse_text_line(
        "X300pro 12+256",
        sheet_name="VIVO",
        quote_date=QUOTE_DATE,
    )
    assert len(items) == 1
    assert items[0].price_status == PriceStatus.NO_QUOTE
    assert items[0].price is None


def test_preserves_masked_price() -> None:
    items = parse_text_line(
        "红米Note15pro 12+512 黑18*0白18*0",
        sheet_name="红米小米",
        quote_date=QUOTE_DATE,
    )
    assert len(items) == 2
    assert all(item.price_status == PriceStatus.MASKED for item in items)


def test_ignores_layout_placeholder() -> None:
    assert parse_text_line("325", sheet_name="OPPO", quote_date=QUOTE_DATE) == []


def test_strips_repeated_brand_from_model() -> None:
    items = parse_text_line(
        "OPPOK12s 8+128黑1260白1265紫1265",
        sheet_name="OPPO",
        quote_date=QUOTE_DATE,
    )
    assert {item.model for item in items} == {"K12s"}


def test_splits_colors_when_price_is_missing() -> None:
    items = parse_text_line(
        "一加Ace5 12+256 黑钛*",
        sheet_name="OPPO",
        quote_date=QUOTE_DATE,
    )
    assert {item.model for item in items} == {"Ace5"}
    assert {item.color for item in items} == {"黑", "钛"}
    assert all(item.price_status == PriceStatus.MASKED for item in items)
