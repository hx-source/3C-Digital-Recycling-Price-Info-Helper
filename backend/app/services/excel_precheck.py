from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal

from app.models.entities import PriceQuote, PriceStatus
from app.services.normalizer import model_key
from app.services.parser import ParsedCandidate
from app.services.quote_service import ABNORMAL_CHANGE_THRESHOLD


@dataclass(slots=True)
class ExcelPrecheckReport:
    items: list[ParsedCandidate]
    normal_items: list[ParsedCandidate]
    issues: list[dict]
    records: list[dict]
    incomplete_candidates: int
    no_quote_candidates: int
    masked_candidates: int
    duplicate_candidates: int
    abnormal_price_candidates: int

    def as_dict(self) -> dict:
        return {
            "total_candidates": len(self.items),
            "normal_candidates": len(self.normal_items),
            "needs_review_candidates": len(self.items) - len(self.normal_items),
            "incomplete_candidates": self.incomplete_candidates,
            "no_quote_candidates": self.no_quote_candidates,
            "masked_candidates": self.masked_candidates,
            "duplicate_candidates": self.duplicate_candidates,
            "abnormal_price_candidates": self.abnormal_price_candidates,
            "issues": self.issues[:24],
            "records": self.records,
        }


def _identity(item: ParsedCandidate) -> str:
    return model_key(item.brand, item.model_normalized, item.storage, item.color, item.variant)


def inspect_excel_candidates(
    items: list[ParsedCandidate],
    existing_quotes: list[PriceQuote],
) -> ExcelPrecheckReport:
    """Assess parsed Excel rows without writing anything to the database."""
    identities = [_identity(item) for item in items]
    file_counts = Counter((item.quote_date, identity) for item, identity in zip(items, identities, strict=True))
    existing_same_day = {(quote.quote_date, quote.model_key) for quote in existing_quotes}
    existing_same_day_quotes = {(quote.quote_date, quote.model_key): quote for quote in existing_quotes}
    file_locations: dict[tuple[object, str], list[str]] = {}
    for item, identity in zip(items, identities, strict=True):
        key = (item.quote_date, identity)
        location = "!".join(part for part in (item.sheet_name, item.cell_address) if part)
        file_locations.setdefault(key, []).append(location or "当前表格")
    latest_history: dict[str, PriceQuote] = {}
    for quote in existing_quotes:
        if quote.price_status != PriceStatus.QUOTED or quote.price is None:
            continue
        current = latest_history.get(quote.model_key)
        if current is None or (quote.quote_date, quote.id) > (current.quote_date, current.id):
            latest_history[quote.model_key] = quote

    normal_items: list[ParsedCandidate] = []
    issues: list[dict] = []
    counters = Counter()
    for item, identity in zip(items, identities, strict=True):
        reasons: list[str] = []
        duplicate_detail: str | None = None
        previous_price: Decimal | None = None
        difference: Decimal | None = None
        if not item.brand or item.brand == "Other" or not item.model or not item.model_normalized:
            reasons.append("信息不完整")
            counters["incomplete"] += 1
        if item.price_status == PriceStatus.NO_QUOTE:
            reasons.append("暂无报价")
            counters["no_quote"] += 1
        if item.price_status == PriceStatus.MASKED:
            reasons.append("价格待确认（含通配符）")
            counters["masked"] += 1
        duplicate_key = (item.quote_date, identity)
        duplicate_in_file = file_counts[duplicate_key] > 1
        duplicate_in_history = duplicate_key in existing_same_day
        if duplicate_in_file or duplicate_in_history:
            reasons.append("重复报价")
            counters["duplicate"] += 1
            notes: list[str] = []
            if duplicate_in_file:
                locations = [location for location in file_locations[duplicate_key] if location]
                notes.append(f"当前表中有 {file_counts[duplicate_key]} 条相同型号规格：{'、'.join(locations[:4])}")
            if duplicate_in_history:
                quote = existing_same_day_quotes[duplicate_key]
                notes.append(f"与已发布的同日报价重复（来源：{quote.source_name}）")
            duplicate_detail = "；".join(notes)

        previous = latest_history.get(identity)
        if (
            item.price_status == PriceStatus.QUOTED
            and item.price is not None
            and previous is not None
            and previous.quote_date < item.quote_date
        ):
            previous_price = Decimal(previous.price)
            difference = item.price - previous_price
            if abs(difference) >= ABNORMAL_CHANGE_THRESHOLD:
                reasons.append(f"价格波动≥{ABNORMAL_CHANGE_THRESHOLD}")
                counters["abnormal"] += 1

        if reasons:
            issues.append(
                {
                    "reasons": reasons,
                    "sheet_name": item.sheet_name,
                    "cell_address": item.cell_address,
                    "brand": item.brand,
                    "model": item.model,
                    "storage": item.storage,
                    "color": item.color,
                    "price_status": item.price_status,
                    "price": item.price,
                    "previous_price": previous_price,
                    "difference": difference,
                    "raw_text": item.raw_text,
                    "duplicate_detail": duplicate_detail,
                }
            )
        else:
            normal_items.append(item)

    records = [
        {
            "reasons": [],
            "sheet_name": item.sheet_name,
            "cell_address": item.cell_address,
            "brand": item.brand,
            "model": item.model,
            "storage": item.storage,
            "color": item.color,
            "price_status": item.price_status,
            "price": item.price,
            "previous_price": None,
            "difference": None,
            "raw_text": item.raw_text,
            "duplicate_detail": None,
        }
        for item in normal_items
    ]
    records.extend(issues)
    records.sort(key=lambda record: (bool(record["reasons"]), record["sheet_name"] or "", record["cell_address"] or ""))

    return ExcelPrecheckReport(
        items=items,
        normal_items=normal_items,
        issues=issues,
        records=records,
        incomplete_candidates=counters["incomplete"],
        no_quote_candidates=counters["no_quote"],
        masked_candidates=counters["masked"],
        duplicate_candidates=counters["duplicate"],
        abnormal_price_candidates=counters["abnormal"],
    )
