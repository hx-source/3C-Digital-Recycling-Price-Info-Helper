from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.quotes import ForecastBacktestResponse, PriceForecastResponse
from app.services.forecast_service import ForecastError, forecast_backtest, generate_price_forecast


router = APIRouter()


@router.get("/price", response_model=PriceForecastResponse)
def price_forecast(
    query: str = Query(min_length=1, max_length=200),
    horizons: str = Query(default="1,3,7,10"),
    with_external: bool = True,
    db: Session = Depends(get_db),
) -> PriceForecastResponse:
    try:
        parsed_horizons = [int(item.strip()) for item in horizons.split(",") if item.strip()]
        return generate_price_forecast(db, query, parsed_horizons, with_external)
    except (ForecastError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/backtest", response_model=ForecastBacktestResponse)
def backtest(model_key: str | None = Query(default=None, max_length=500), db: Session = Depends(get_db)):
    return forecast_backtest(db, model_key)
