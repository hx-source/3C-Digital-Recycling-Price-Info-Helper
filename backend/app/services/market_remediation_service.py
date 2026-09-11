from __future__ import annotations

import json
import re
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.entities import MarketMonitorFinding, PriceQuote, PriceStatus
from app.services.agent_service import AgentUnavailableError, _ollama_chat
from app.services.audit_service import AGENT, HUMAN, add_audit_log, candidate_snapshot


class FindingActionError(ValueError):
    pass


def _load_finding(db: Session, finding_id: int) -> MarketMonitorFinding:
    finding = db.get(MarketMonitorFinding, finding_id)
    if not finding:
        raise FindingActionError("监控异常不存在")
    return finding


def _previous_quote(db: Session, quote: PriceQuote) -> PriceQuote | None:
    return db.scalar(
        select(PriceQuote)
        .where(PriceQuote.model_key == quote.model_key, PriceQuote.quote_date < quote.quote_date)
        .order_by(PriceQuote.quote_date.desc(), PriceQuote.id.desc())
        .limit(1)
    )


def _diagnosis_evidence(db: Session, finding: MarketMonitorFinding) -> tuple[dict, Decimal | None, str | None, float]:
    evidence = dict(finding.evidence or {})
    proposed: Decimal | None = None
    confidence = 0.65
    quote = db.get(PriceQuote, finding.quote_id) if finding.quote_id else None
    if not quote:
        evidence["source_check"] = "该异常是汇总或结构问题，没有可直接修改的单条报价"
        return evidence, None, None, confidence

    previous = _previous_quote(db, quote)
    candidate = quote.candidate
    evidence.update({
        "current_quote_id": quote.id,
        "candidate_id": quote.candidate_id,
        "current_price": str(quote.price),
        "previous_price": str(previous.price) if previous and previous.price is not None else None,
        "source_text": candidate.raw_text,
        "source_position": candidate.cell_address or f"第 {candidate.source_line or '?'} 行",
    })
    wildcard_price = bool(re.search(r"\d\s*[*＊xX×]+|[*＊xX×]+\s*\d", candidate.raw_text))
    if wildcard_price:
        evidence["reason_code"] = "来源价格包含通配数字，不能作为精确报价"
        evidence["suggested_status"] = "masked"
        return evidence, None, "masked", 0.98
    if previous and quote.price and previous.price:
        current_price, previous_price = Decimal(quote.price), Decimal(previous.price)
        ratio = current_price / previous_price
        evidence["price_ratio"] = f"{ratio:.3f}"
        if ratio <= Decimal("0.25") or ratio >= Decimal("4"):
            proposed = previous_price
            confidence = 0.94
            evidence["reason_code"] = "价格位数或小数点疑似错误"
        elif abs(current_price - previous_price) >= Decimal("1000"):
            confidence = 0.82
            evidence["reason_code"] = "涨跌远超常规区间，需要核对原始数据"
        else:
            evidence["reason_code"] = "存在明显波动，但可能是真实行情变化"
    return evidence, proposed, None, confidence


def _fallback_diagnosis(finding: MarketMonitorFinding, evidence: dict, proposed: Decimal | None, proposed_status: str | None) -> tuple[str, str]:
    if not finding.quote_id:
        return (
            "这是跨记录或数据结构异常，无法归因到一条可直接改价的报价。",
            "检查导入批次、所属板块和相邻规格，确认是缺货、漏入还是结构变化后再处理。",
        )
    if proposed_status == "masked":
        return (
            "来源价格含通配数字，每个通配符代表一位未知数字，当前记录不应作为精确价格参与涨跌计算。",
            "建议将该报价恢复为“价格区间/掩码”状态并清空精确价格，保留原文供后续人工询价。",
        )
    source_text = evidence.get("source_text") or "原始记录"
    if proposed is not None:
        return (
            f"当前价与上一期价格比例极端，且来源为“{source_text}”，更像价格位数识别或录入错误。",
            f"建议先核对来源位置；若原文支持，可将价格修正为 {proposed:.0f} 元。执行前必须人工确认。",
        )
    return (
        f"已核对当前价、上一期价格及来源“{source_text}”，目前证据不足以自动推定正确价格。",
        "建议查看原始单元格或图片位置，确认是真实行情波动还是录入错误；暂不自动给出改价值。",
    )


def _model_diagnosis(finding: MarketMonitorFinding, evidence: dict, fallback: tuple[str, str]) -> tuple[str, str, bool]:
    try:
        response = _ollama_chat({
            "model": settings.ollama_model,
            "messages": [
                {"role": "system", "content": "你是3C回收报价异常处置智能体。只根据证据输出严格JSON，字段为diagnosis和recommendation。不得改变建议价格，不得虚构原文；各字段不超过100字。"},
                {"role": "user", "content": json.dumps({"finding": finding.title, "detail": finding.detail, "evidence": evidence, "fixed_proposed_price": str(finding.proposed_price) if finding.proposed_price else None}, ensure_ascii=False)},
            ],
            "format": "json", "stream": False, "keep_alive": "10m", "options": {"temperature": 0, "num_predict": 220},
        })
        payload = json.loads(str((response.get("message") or {}).get("content") or "{}"))
        diagnosis = str(payload.get("diagnosis") or "").strip()
        recommendation = str(payload.get("recommendation") or "").strip()
        if diagnosis and recommendation:
            return diagnosis[:500], recommendation[:500], True
    except (AgentUnavailableError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return fallback[0], fallback[1], False


def diagnose_finding(db: Session, finding_id: int) -> MarketMonitorFinding:
    finding = _load_finding(db, finding_id)
    if finding.handling_status in {"resolved", "dismissed"}:
        raise FindingActionError("该异常已经处理，不能重复诊断")
    evidence, proposed, proposed_status, confidence = _diagnosis_evidence(db, finding)
    finding.proposed_price = proposed
    finding.proposed_price_status = proposed_status
    finding.diagnosis_confidence = confidence
    finding.diagnosis_run_id = str(uuid4())
    fallback = _fallback_diagnosis(finding, evidence, proposed, proposed_status)
    finding.diagnosis, finding.recommendation, finding.diagnosis_generated_by_model = _model_diagnosis(finding, evidence, fallback)
    finding.diagnosis_model = settings.ollama_model if finding.diagnosis_generated_by_model else None
    finding.handling_status = "diagnosed"
    finding.evidence = {key: None if value is None else str(value) for key, value in evidence.items()}
    db.commit()
    db.refresh(finding)
    return finding


def apply_finding_price(
    db: Session,
    finding_id: int,
    proposed_price: Decimal | None,
    proposed_price_status: str | None,
    reason: str | None,
) -> MarketMonitorFinding:
    finding = _load_finding(db, finding_id)
    if finding.handling_status != "diagnosed":
        raise FindingActionError("请先运行智能诊断，再确认执行")
    quote = db.get(PriceQuote, finding.quote_id) if finding.quote_id else None
    if not quote:
        raise FindingActionError("该异常没有可修改的单条报价")
    if finding.proposed_price is None and finding.proposed_price_status is None:
        raise FindingActionError("智能体没有给出可安全执行的建议价格，请前往复核工作台人工核对")
    if proposed_price != finding.proposed_price or proposed_price_status != finding.proposed_price_status:
        raise FindingActionError("提交价格与智能体建议不一致，请重新诊断")

    candidate = quote.candidate
    before = candidate_snapshot(candidate)
    if proposed_price_status == "masked":
        quote.price_status = PriceStatus.MASKED
        candidate.price_status = PriceStatus.MASKED
        quote.price = None
        candidate.price = None
    else:
        quote.price = proposed_price
        candidate.price = proposed_price
    candidate.review_note = f"行情异常处置：{reason or finding.recommendation or finding.title}"[:500]
    after = candidate_snapshot(candidate)
    add_audit_log(
        db, action_type="monitor_remediation_apply", operator_type=HUMAN,
        before_data=before, after_data=after, batch_id=quote.batch_id, candidate_id=quote.candidate_id,
        reason=reason or finding.recommendation, agent_run_id=finding.diagnosis_run_id,
        model_name=finding.diagnosis_model, rule_version="market-remediation-v1",
    )
    finding.handling_status = "resolved"
    finding.handled_reason = (reason or "人工确认采用智能体建议")[:500]
    finding.handled_at = datetime.now()
    db.commit()
    db.refresh(finding)
    return finding


def dismiss_finding(db: Session, finding_id: int, reason: str | None) -> MarketMonitorFinding:
    finding = _load_finding(db, finding_id)
    if finding.handling_status == "resolved":
        raise FindingActionError("已执行修正的异常不能再忽略")
    finding.handling_status = "dismissed"
    finding.handled_reason = (reason or "人工确认无需处理")[:500]
    finding.handled_at = datetime.now()
    db.commit()
    db.refresh(finding)
    return finding
