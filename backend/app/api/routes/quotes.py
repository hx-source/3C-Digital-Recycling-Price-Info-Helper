from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.entities import PriceQuote, PriceStatus
from app.schemas.quotes import PriceChangeRead, QuotePage, QuoteRead, TrendPoint
from app.services.quote_service import price_changes


router = APIRouter()


@router.get("", response_model=QuotePage)
def list_quotes(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=300),
    brand: str | None = None,
    category: str | None = None,
    quote_date: date | None = None,
    price_status: PriceStatus | None = None,
    search: str | None = None,
) -> QuotePage:
    filters = []
    if brand:
        filters.append(PriceQuote.brand == brand)
    if category:
        filters.append(PriceQuote.category == category)
    if quote_date:
        filters.append(PriceQuote.quote_date == quote_date)
    if price_status:
        filters.append(PriceQuote.price_status == price_status)
    if search:
        pattern = f"%{search}%"
        filters.append(or_(PriceQuote.model.ilike(pattern), PriceQuote.color.ilike(pattern)))
    total = db.scalar(select(func.count()).select_from(PriceQuote).where(*filters)) or 0
    items = db.scalars(
        select(PriceQuote)
        .where(*filters)
        .order_by(PriceQuote.quote_date.desc(), PriceQuote.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return QuotePage(items=list(items), total=total, page=page, page_size=page_size)


@router.get("/changes", response_model=list[PriceChangeRead])
def get_changes(
    db: Session = Depends(get_db),
    as_of: date | None = None,
    brand: str | None = None,
    category: str | None = None,
    search: str | None = None,
    limit: int = Query(500, ge=1, le=5000),
) -> list[PriceChangeRead]:
    return price_changes(db, as_of=as_of, brand=brand, category=category, search=search, limit=limit)


@router.get("/{model_key:path}/history", response_model=list[TrendPoint])
def get_history(model_key: str, db: Session = Depends(get_db)) -> list[TrendPoint]:
    rows = db.scalars(
        select(PriceQuote)
        .where(
            PriceQuote.model_key == model_key,
            PriceQuote.price_status == PriceStatus.QUOTED,
            PriceQuote.price.is_not(None),
        )
        .order_by(PriceQuote.quote_date, PriceQuote.id)
    ).all()
    if not rows:
        raise HTTPException(status_code=404, detail="没有该型号的价格历史")
    by_date: dict[date, PriceQuote] = {}
    for row in rows:
        by_date[row.quote_date] = row
    return [TrendPoint(quote_date=key, price=value.price) for key, value in sorted(by_date.items())]


@router.get("/meta/brands", response_model=list[str])
def list_brands(db: Session = Depends(get_db)) -> list[str]:
    return list(db.scalars(select(PriceQuote.brand).distinct().order_by(PriceQuote.brand)).all())
