from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.entities import MarketMonitorFinding, MarketMonitorRun, MonitorRunStatus, PriceQuote, PriceStatus
from app.services.agent_service import AgentUnavailableError, _ollama_chat
from app.services.quote_service import price_changes


def create_monitor_run(db: Session, *, batch_id: int | None, trigger_type: str) -> MarketMonitorRun:
    latest_date = db.scalar(select(func.max(PriceQuote.quote_date)))
    run = MarketMonitorRun(
        id=str(uuid4()), batch_id=batch_id, trigger_type=trigger_type,
        status=MonitorRunStatus.QUEUED, quote_date=latest_date,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _finding(run_id: str, finding_type: str, severity: str, title: str, detail: str, **evidence) -> MarketMonitorFinding:
    return MarketMonitorFinding(
        run_id=run_id, finding_type=finding_type, severity=severity,
        brand=evidence.pop("brand", None), model=evidence.pop("model", None),
        quote_id=evidence.pop("quote_id", None),
        title=title, detail=detail, evidence={key: str(value) for key, value in evidence.items()},
    )


def _capacity(storage: str | None) -> int | None:
    if not storage:
        return None
    match = re.search(r"(?:\d{1,2}\+)?(\d{2,4}|1[Tt])", storage.replace(" ", ""))
    if not match:
        return None
    return 1024 if match.group(1).lower() == "1t" else int(match.group(1))


def _fallback_summary(run: MarketMonitorRun, findings: list[MarketMonitorFinding]) -> str:
    if not findings:
        return f"{run.quote_date} 共扫描 {run.scanned_quotes} 条有效报价，未发现达到监控阈值的明显异常。"
    labels = defaultdict(int)
    for item in findings:
        labels[item.finding_type] += 1
    detail = "、".join(f"{label} {count} 项" for label, count in labels.items())
    return f"{run.quote_date} 共扫描 {run.scanned_quotes} 条报价，发现 {len(findings)} 项关注点：{detail}。建议优先处理高风险价格异常。"


def _model_summary(run: MarketMonitorRun, findings: list[MarketMonitorFinding], fallback: str) -> tuple[str, bool]:
    evidence = [{"severity": item.severity, "type": item.finding_type, "title": item.title, "detail": item.detail} for item in findings[:30]]
    try:
        response = _ollama_chat({
            "model": settings.ollama_model,
            "messages": [
                {"role": "system", "content": "你是3C回收行情监控智能体。仅根据给定监控证据生成120字以内中文日报，不得新增数字。先概括整体，再指出最值得关注的两类风险和处理顺序。"},
                {"role": "user", "content": json.dumps({"date": str(run.quote_date), "scanned": run.scanned_quotes, "findings": evidence}, ensure_ascii=False)},
            ],
            "stream": False, "keep_alive": "10m", "options": {"temperature": 0, "num_predict": 180},
        })
        summary = str((response.get("message") or {}).get("content") or "").strip()
        return (summary, True) if summary else (fallback, False)
    except AgentUnavailableError:
        return fallback, False


def analyze_monitor_run(db: Session, run: MarketMonitorRun) -> MarketMonitorRun:
    run.status = MonitorRunStatus.RUNNING
    run.started_at = datetime.now()
    run.error_message = None
    db.commit()
    try:
        latest = db.scalar(select(func.max(PriceQuote.quote_date)).where(PriceQuote.price_status == PriceStatus.QUOTED))
        if not latest:
            raise ValueError("当前没有已发布的明确报价")
        previous = db.scalar(select(func.max(PriceQuote.quote_date)).where(PriceQuote.quote_date < latest))
        run.quote_date, run.previous_date = latest, previous
        current = list(db.scalars(select(PriceQuote).where(
            PriceQuote.quote_date == latest, PriceQuote.price_status == PriceStatus.QUOTED, PriceQuote.price.is_not(None)
        )))
        run.scanned_quotes = len(current)
        findings: list[MarketMonitorFinding] = []
        current_by_key = {row.model_key: row for row in current}

        for item in price_changes(db, as_of=latest, limit=10000):
            if item.current_date != latest or item.change_amount is None or abs(item.change_amount) < Decimal("500"):
                continue
            severity = "danger" if abs(item.change_amount) >= Decimal("1000") else "warning"
            direction = "上涨" if item.change_amount > 0 else "下跌"
            current_quote = current_by_key.get(item.model_key)
            findings.append(_finding(
                run.id, "价格异常", severity,
                f"{item.brand} {item.model} {direction} {abs(item.change_amount):.0f} 元",
                f"{item.storage or '未标容量'} · {item.color or '未标颜色'}：{item.previous_price} 元 → {item.current_price} 元。",
                brand=item.brand, model=item.model, previous_price=item.previous_price,
                current_price=item.current_price, change_amount=item.change_amount,
                quote_id=current_quote.id if current_quote else None,
            ))

        if previous:
            previous_rows = list(db.scalars(select(PriceQuote).where(
                PriceQuote.quote_date == previous, PriceQuote.price_status == PriceStatus.QUOTED
            )))
            if previous_rows and len(current) < len(previous_rows) * 0.7:
                findings.append(_finding(
                    run.id, "数据量异常", "danger", "本期报价数量明显减少",
                    f"本期 {len(current)} 条，上期 {len(previous_rows)} 条，可能存在工作表、板块或型号漏入。",
                    current_count=len(current), previous_count=len(previous_rows), ratio=round(len(current) / len(previous_rows) * 100, 1),
                ))
            current_keys = {row.model_key for row in current}
            previous_keys = {row.model_key for row in previous_rows}
            new_count, missing_count = len(current_keys - previous_keys), len(previous_keys - current_keys)
            if new_count:
                findings.append(_finding(run.id, "新增型号", "info", f"发现 {new_count} 个新增报价规格", "这些规格在上一报价日中未出现，建议确认是否为新品或重新到货。", count=new_count))
            if missing_count:
                severity = "warning" if missing_count >= max(10, len(previous_keys) * 0.1) else "info"
                findings.append(_finding(run.id, "型号消失", severity, f"有 {missing_count} 个上期规格未出现", "可能为缺货、停报或导入遗漏，可结合数据量异常一起检查。", count=missing_count))

        by_model_storage: dict[tuple[str, str, str | None, str | None], list[PriceQuote]] = defaultdict(list)
        by_variant: dict[tuple[str, str, str | None], list[PriceQuote]] = defaultdict(list)
        for row in current:
            by_model_storage[(row.brand, row.model_normalized, row.color, row.variant)].append(row)
            by_variant[(row.brand, row.model_normalized, row.storage)].append(row)
        for rows in by_model_storage.values():
            by_capacity: dict[int, PriceQuote] = {}
            for row in rows:
                cap = _capacity(row.storage)
                if cap is not None:
                    by_capacity.setdefault(cap, row)
            ordered = sorted(by_capacity.items(), key=lambda x: x[0])
            for (small_cap, small), (large_cap, large) in zip(ordered, ordered[1:]):
                if Decimal(small.price or 0) > Decimal(large.price or 0) + Decimal("100"):
                    findings.append(_finding(run.id, "容量倒挂", "warning", f"{small.brand} {small.model} 容量价格倒挂", f"{small.storage} 为 {small.price} 元，高于 {large.storage} 的 {large.price} 元。", brand=small.brand, model=small.model, small_capacity=small_cap, large_capacity=large_cap))
                    break
        for rows in by_variant.values():
            prices = [Decimal(row.price or 0) for row in rows]
            if len(prices) >= 2 and max(prices) - min(prices) >= Decimal("300"):
                row = rows[0]
                findings.append(_finding(run.id, "颜色价差", "warning", f"{row.brand} {row.model} 同规格颜色价差较大", f"{row.storage or '未标容量'} 的不同颜色相差 {max(prices) - min(prices):.0f} 元。", brand=row.brand, model=row.model, spread=max(prices) - min(prices)))

        db.add_all(findings[:300])
        run.finding_count = len(findings[:300])
        run.danger_count = sum(item.severity == "danger" for item in findings[:300])
        run.warning_count = sum(item.severity == "warning" for item in findings[:300])
        fallback = _fallback_summary(run, findings[:300])
        run.summary, run.generated_by_model = _model_summary(run, findings[:300], fallback)
        run.model_name = settings.ollama_model if run.generated_by_model else None
        run.status = MonitorRunStatus.COMPLETED
        run.completed_at = datetime.now()
    except Exception as exc:
        run.status = MonitorRunStatus.FAILED
        run.error_message = f"{type(exc).__name__}: {exc}"
        run.completed_at = datetime.now()
    db.commit()
    db.refresh(run)
    return run


def run_market_monitor(run_id: str) -> None:
    with SessionLocal() as db:
        run = db.get(MarketMonitorRun, run_id)
        if run:
            analyze_monitor_run(db, run)
