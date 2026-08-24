from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.entities import (
    BatchStatus,
    ImportBatch,
    PriceQuote,
    PriceStatus,
    QuoteCandidate,
    ReviewStatus,
)
from app.schemas.quotes import DashboardSummary, PriceChangeRead
from app.services.normalizer import model_key, normalize_model


ABNORMAL_CHANGE_THRESHOLD = Decimal("500")


def update_candidate(candidate: QuoteCandidate, payload: dict[str, object]) -> QuoteCandidate:
    for field, value in payload.items():
        setattr(candidate, field, value)
    if "model" in payload and payload["model"]:
        candidate.model_normalized = normalize_model(str(payload["model"]))
    if candidate.price_status == PriceStatus.QUOTED and candidate.price is None:
        raise ValueError("price_status 为 quoted 时必须填写价格")
    if candidate.price_status != PriceStatus.QUOTED:
        candidate.price = None
    return candidate


def commit_batch(db: Session, batch: ImportBatch) -> tuple[int, int]:
    pending = db.scalar(
        select(func.count()).select_from(QuoteCandidate).where(
            QuoteCandidate.batch_id == batch.id,
            QuoteCandidate.review_status == ReviewStatus.PENDING,
        )
    )
    if pending:
        raise ValueError(f"仍有 {pending} 条候选数据未复核")

    approved = db.scalars(
        select(QuoteCandidate).where(
            QuoteCandidate.batch_id == batch.id,
            QuoteCandidate.review_status == ReviewStatus.APPROVED,
        )
    ).all()
    inserted = 0
    skipped = 0
    for candidate in approved:
        exists = db.scalar(select(PriceQuote.id).where(PriceQuote.candidate_id == candidate.id))
        if exists:
            skipped += 1
            continue
        db.add(
            PriceQuote(
                batch_id=batch.id,
                candidate_id=candidate.id,
                source_name=batch.source_name,
                quote_date=candidate.quote_date,
                category=candidate.category,
                brand=candidate.brand,
                model=candidate.model,
                model_normalized=candidate.model_normalized,
                storage=candidate.storage,
                color=candidate.color,
                variant=candidate.variant,
                model_key=model_key(
                    candidate.brand,
                    candidate.model_normalized,
                    candidate.storage,
                    candidate.color,
                    candidate.variant,
                ),
                price_status=candidate.price_status,
                price=candidate.price,
            )
        )
        inserted += 1
    if not approved:
        raise ValueError("没有已通过的候选数据")
    batch.status = BatchStatus.COMMITTED
    batch.committed_at = datetime.now()
    batch.valid_candidates = len(approved)
    db.commit()
    return inserted, skipped


def price_changes(
    db: Session,
    *,
    as_of: date | None = None,
    brand: str | None = None,
    category: str | None = None,
    search: str | None = None,
    limit: int = 500,
) -> list[PriceChangeRead]:
    query = select(PriceQuote).where(
        PriceQuote.price_status == PriceStatus.QUOTED,
        PriceQuote.price.is_not(None),
    )
    if as_of:
        query = query.where(PriceQuote.quote_date <= as_of)
    if brand:
        query = query.where(PriceQuote.brand == brand)
    if category:
        query = query.where(PriceQuote.category == category)
    if search:
        pattern = f"%{search}%"
        query = query.where(
            or_(PriceQuote.model.ilike(pattern), PriceQuote.storage.ilike(pattern), PriceQuote.color.ilike(pattern))
        )
    rows = db.scalars(query.order_by(PriceQuote.model_key, PriceQuote.quote_date.desc(), PriceQuote.id.desc())).all()
    grouped: dict[str, list[PriceQuote]] = defaultdict(list)
    for row in rows:
        grouped[row.model_key].append(row)

    output: list[PriceChangeRead] = []
    for key, quotes in grouped.items():
        current = quotes[0]
        previous = next((item for item in quotes[1:] if item.quote_date < current.quote_date), None)
        current_price = Decimal(current.price or 0)
        previous_price = Decimal(previous.price) if previous and previous.price is not None else None
        change = current_price - previous_price if previous_price is not None else None
        percent = float(change / previous_price * 100) if change is not None and previous_price else None
        requires_review = change is not None and abs(change) >= ABNORMAL_CHANGE_THRESHOLD
        output.append(
            PriceChangeRead(
                model_key=key,
                brand=current.brand,
                model=current.model,
                storage=current.storage,
                color=current.color,
                variant=current.variant,
                current_date=current.quote_date,
                current_price=current_price,
                previous_date=previous.quote_date if previous else None,
                previous_price=previous_price,
                change_amount=change,
                change_percent=round(percent, 2) if percent is not None else None,
                requires_review=requires_review,
            )
        )
    output.sort(key=lambda item: (item.current_date, abs(item.change_amount or 0)), reverse=True)
    return output[:limit]


def dashboard_summary(db: Session) -> DashboardSummary:
    latest_date = db.scalar(
        select(func.max(PriceQuote.quote_date)).where(
            PriceQuote.price_status == PriceStatus.QUOTED,
            PriceQuote.price.is_not(None),
        )
    )
    published = db.scalar(select(func.count()).select_from(PriceQuote)) or 0
    pending = db.scalar(
        select(func.count()).select_from(QuoteCandidate).where(
            QuoteCandidate.review_status == ReviewStatus.PENDING
        )
    ) or 0
    changes = price_changes(db, as_of=latest_date, limit=5000) if latest_date else []
    today = [
        item for item in changes
        if item.current_date == latest_date and item.change_amount is not None and not item.requires_review
    ]
    increases = sorted((item for item in today if item.change_amount and item.change_amount > 0), key=lambda x: x.change_amount, reverse=True)
    decreases = sorted((item for item in today if item.change_amount and item.change_amount < 0), key=lambda x: x.change_amount)
    unchanged = sum(1 for item in today if item.change_amount == 0)
    return DashboardSummary(
        latest_quote_date=latest_date,
        published_quotes=published,
        pending_candidates=pending,
        today_increases=len(increases),
        today_decreases=len(decreases),
        today_unchanged=unchanged,
        top_increases=increases[:8],
        top_decreases=decreases[:8],
    )
