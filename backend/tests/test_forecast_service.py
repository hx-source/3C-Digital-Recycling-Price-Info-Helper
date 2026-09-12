from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.entities import PriceForecast, PriceQuote, PriceStatus
from app.services.forecast_service import ForecastError, forecast_backtest, generate_price_forecast


MODEL_KEY = "redmi|k80|12+256|黑色|"


def quote(candidate_id: int, quote_date: date, price: str) -> PriceQuote:
    return PriceQuote(
        batch_id=1,
        candidate_id=candidate_id,
        source_name="测试来源",
        quote_date=quote_date,
        category="手机",
        brand="Redmi",
        model="K80",
        model_normalized="K80",
        storage="12+256",
        color="黑色",
        variant=None,
        model_key=MODEL_KEY,
        price_status=PriceStatus.QUOTED,
        price=Decimal(price),
    )


def test_forecast_returns_bounded_multi_horizon_result_without_external_network() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([
            quote(1, date(2026, 9, 7), "2100"),
            quote(2, date(2026, 9, 8), "2120"),
            quote(3, date(2026, 9, 9), "2110"),
            quote(4, date(2026, 9, 10), "2140"),
        ])
        db.commit()

        result = generate_price_forecast(db, "Redmi K80 12+256 黑色", [1, 3, 7, 10], with_external=False)

        assert result.model_key == MODEL_KEY
        assert [item.horizon_days for item in result.forecasts] == [1, 3, 7, 10]
        assert all(item.lower_price <= item.predicted_price <= item.upper_price for item in result.forecasts)
        assert all(item.horizon_days <= 10 for item in result.forecasts)
        assert result.generated_by_model is False
        assert len(list(db.scalars(select(PriceForecast)))) == 4


def test_forecast_rejects_period_longer_than_ten_days() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        with pytest.raises(ForecastError, match="不能超过 10 天"):
            generate_price_forecast(db, "K80", [11], with_external=False)


def test_backtest_evaluates_forecast_when_target_quote_exists() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([
            quote(1, date(2026, 9, 8), "2100"),
            quote(2, date(2026, 9, 9), "2120"),
            quote(3, date(2026, 9, 10), "2140"),
        ])
        db.commit()
        generate_price_forecast(db, "K80 12+256 黑色", [1], with_external=False)
        db.add(quote(4, date(2026, 9, 11), "2160"))
        db.commit()

        result = forecast_backtest(db, MODEL_KEY)

        assert result.evaluated_count == 1
        assert result.direction_accuracy == 1.0
        assert result.mean_absolute_error is not None
