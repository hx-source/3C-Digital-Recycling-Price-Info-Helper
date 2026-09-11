from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
import re
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.entities import BatchStatus, ImportBatch, PriceQuote, PriceStatus, QuoteCandidate, ReviewStatus
from app.schemas.quotes import (
    CandidateRead,
    ReviewBatchApproveSafeRequest,
    ReviewBatchApproveSafeResponse,
    ReviewBatchDiagnosisItem,
    ReviewBatchDiagnosisResponse,
    ReviewAgentStep,
    ReviewDiagnosisApplyRequest,
    ReviewDiagnosisApplyResponse,
    ReviewDiagnosisChange,
    ReviewDiagnosisEvidence,
    ReviewDiagnosisResponse,
)
from app.services.agent_service import AgentUnavailableError, _ollama_chat
from app.services.normalizer import normalize_model
from app.services.parser import parse_text_line
from app.services.quote_service import ABNORMAL_CHANGE_THRESHOLD, update_candidate
from app.services.audit_service import (
    AGENT,
    HUMAN,
    AGENT_SUGGESTION_APPLY,
    AUTO_APPROVE,
    MARK_NO_ISSUE,
    REVOKE_AUTO_APPROVE,
    add_audit_log,
    candidate_snapshot,
)


AUTO_APPROVE_CONFIDENCE = 0.90
AUTO_APPROVAL_NOTE_PREFIX = "[智能批量审核]"


FIELD_LABELS = {
    "brand": "品牌",
    "model": "型号",
    "storage": "容量",
    "color": "颜色",
    "variant": "版本",
    "price_status": "价格状态",
    "price": "价格",
    "review_status": "复核状态",
}

REVIEW_TOOL_LABELS = {
    "inspect_source": "读取来源证据",
    "compare_history": "比较历史价格",
    "check_duplicates": "检查重复报价",
    "check_source_structure": "检查来源拆分和型号一致性",
    "reparse_source": "重新解析来源原文",
}

REVIEW_AGENT_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "inspect_source",
            "description": "读取当前候选记录的来源板块、位置和原文。每次复核必须先调用。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_history",
            "description": "查询完全相同型号、容量、颜色和版本的上一期已发布价格，判断涨跌异常。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_duplicates",
            "description": "检查当前导入批次是否存在身份和价格都完全相同的重复报价。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_source_structure",
            "description": "检查同一来源行的拆分数量、颜色报价数量和型号是否一致。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reparse_source",
            "description": "当置信度低、型号或价格疑似错误时，用当前解析器重新解析来源原文进行交叉验证。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


class ReviewCandidateNotFoundError(RuntimeError):
    pass


class ReviewBatchNotFoundError(RuntimeError):
    pass


class ReviewDiagnosisConflictError(RuntimeError):
    pass


class ReviewDiagnosisApplyError(RuntimeError):
    pass


@dataclass(slots=True)
class DiagnosisBundle:
    candidate: QuoteCandidate
    signature: str
    severity: str
    issue_types: list[str]
    evidence: list[ReviewDiagnosisEvidence]
    recommendations: list[str]
    proposed_changes: list[ReviewDiagnosisChange]
    source_label: str


@dataclass(slots=True)
class BatchDiagnosisBundle:
    batch: ImportBatch
    signature: str
    candidates: list[QuoteCandidate]
    safe_candidate_ids: list[int]
    risks: list[ReviewBatchDiagnosisItem]
    issue_counts: Counter[str]
    warning_count: int
    danger_count: int


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "value"):
        return value.value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _candidate_signature(candidate: QuoteCandidate) -> str:
    snapshot = {
        "id": candidate.id,
        "updated_at": candidate.updated_at,
        "quote_date": candidate.quote_date,
        "brand": candidate.brand,
        "model": candidate.model,
        "model_normalized": candidate.model_normalized,
        "storage": candidate.storage,
        "color": candidate.color,
        "variant": candidate.variant,
        "price_status": candidate.price_status,
        "price": candidate.price,
        "review_status": candidate.review_status,
        "review_note": candidate.review_note,
        "raw_text": candidate.raw_text,
    }
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, default=_json_value).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _nullable_match(column: Any, value: Any) -> Any:
    return column.is_(None) if value is None else column == value


def _source_group(db: Session, candidate: QuoteCandidate) -> list[QuoteCandidate]:
    # Excel 中一个合并的型号单元格可能被几十条报价共同引用；诊断时还必须
    # 绑定识别原文，避免把整块表格误判为同一条待拆分来源行。
    filters = [
        QuoteCandidate.batch_id == candidate.batch_id,
        QuoteCandidate.raw_text == candidate.raw_text,
    ]
    if candidate.cell_address:
        filters.extend(
            [
                QuoteCandidate.cell_address == candidate.cell_address,
                _nullable_match(QuoteCandidate.sheet_name, candidate.sheet_name),
            ]
        )
    elif candidate.source_line is not None:
        filters.extend(
            [
                QuoteCandidate.source_line == candidate.source_line,
                _nullable_match(QuoteCandidate.sheet_name, candidate.sheet_name),
            ]
        )
    else:
        filters.append(QuoteCandidate.id == candidate.id)
    return list(db.scalars(select(QuoteCandidate).where(*filters).order_by(QuoteCandidate.id)).all())


def _previous_quote(db: Session, candidate: QuoteCandidate) -> PriceQuote | None:
    return db.scalar(
        select(PriceQuote)
        .where(
            PriceQuote.price_status == PriceStatus.QUOTED,
            PriceQuote.price.is_not(None),
            PriceQuote.quote_date < candidate.quote_date,
            PriceQuote.brand == candidate.brand,
            PriceQuote.model_normalized == candidate.model_normalized,
            _nullable_match(PriceQuote.storage, candidate.storage),
            _nullable_match(PriceQuote.color, candidate.color),
            _nullable_match(PriceQuote.variant, candidate.variant),
        )
        .order_by(PriceQuote.quote_date.desc(), PriceQuote.id.desc())
        .limit(1)
    )


def _duplicates(db: Session, candidate: QuoteCandidate) -> list[QuoteCandidate]:
    filters = [
        QuoteCandidate.id != candidate.id,
        QuoteCandidate.batch_id == candidate.batch_id,
        QuoteCandidate.quote_date == candidate.quote_date,
        QuoteCandidate.brand == candidate.brand,
        QuoteCandidate.model_normalized == candidate.model_normalized,
        _nullable_match(QuoteCandidate.storage, candidate.storage),
        _nullable_match(QuoteCandidate.color, candidate.color),
        _nullable_match(QuoteCandidate.variant, candidate.variant),
        QuoteCandidate.price_status == candidate.price_status,
        _nullable_match(QuoteCandidate.price, candidate.price),
    ]
    return list(db.scalars(select(QuoteCandidate).where(*filters).order_by(QuoteCandidate.id)).all())


def _display_value(value: Any) -> str | Decimal | None:
    if value is None:
        return None
    if hasattr(value, "value"):
        return str(value.value)
    return value


def _change(
    candidate: QuoteCandidate,
    field: str,
    suggested_value: Any,
    reason: str,
) -> ReviewDiagnosisChange:
    return ReviewDiagnosisChange(
        field=field,
        label=FIELD_LABELS[field],
        current_value=_display_value(getattr(candidate, field)),
        suggested_value=_display_value(suggested_value),
        reason=reason,
    )


def _append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _identity_key(candidate: QuoteCandidate) -> tuple[Any, ...]:
    return (
        candidate.quote_date,
        candidate.brand,
        candidate.model_normalized,
        candidate.storage,
        candidate.color,
        candidate.variant,
        candidate.price_status.value,
        str(candidate.price) if candidate.price is not None else None,
    )


def _history_key(candidate: QuoteCandidate | PriceQuote) -> tuple[Any, ...]:
    return (
        candidate.brand,
        candidate.model_normalized,
        candidate.storage,
        candidate.color,
        candidate.variant,
    )


def _source_key(candidate: QuoteCandidate) -> tuple[Any, ...]:
    if candidate.cell_address:
        location = ("cell", candidate.sheet_name, candidate.cell_address)
    elif candidate.source_line is not None:
        location = ("line", candidate.sheet_name, candidate.source_line)
    else:
        location = ("record", candidate.id)
    return (*location, candidate.raw_text)


def _batch_signature(batch: ImportBatch, candidates: list[QuoteCandidate]) -> str:
    snapshot = {
        "batch_id": batch.id,
        "status": batch.status,
        "quote_date": batch.quote_date,
        "candidates": [_candidate_signature(item) for item in candidates],
    }
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, default=_json_value).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _batch_risk_suggestion(issues: list[str]) -> str:
    suggestions: list[str] = []
    if "重复报价" in issues:
        suggestions.append("对照来源后保留一条正确报价")
    if "价格异常波动" in issues:
        suggestions.append("核对上一期价格和当前来源")
    if "来源行拆分不一致" in issues or "型号可能不一致" in issues:
        suggestions.append("打开整行检查型号、颜色与价格对应关系")
    if "信息不完整" in issues:
        suggestions.append("补全型号或明确价格状态")
    if "低置信度" in issues:
        suggestions.append("查看原图或表格来源并人工确认")
    if "置信度未达自动通过标准" in issues:
        suggestions.append("数据暂不自动通过，建议快速对照来源")
    return f"发现{'、'.join(issues)}；{'；'.join(suggestions[:2])}。"


def _scan_batch(db: Session, batch_id: int) -> BatchDiagnosisBundle:
    batch = db.get(ImportBatch, batch_id)
    if not batch:
        raise ReviewBatchNotFoundError("导入批次不存在")

    candidates = list(
        db.scalars(select(QuoteCandidate).where(QuoteCandidate.batch_id == batch_id).order_by(QuoteCandidate.id)).all()
    )
    duplicate_counts = Counter(_identity_key(item) for item in candidates)
    source_groups: dict[tuple[Any, ...], list[QuoteCandidate]] = defaultdict(list)
    for candidate in candidates:
        source_groups[_source_key(candidate)].append(candidate)

    parsed_counts: dict[tuple[Any, ...], int | None] = {}
    for key, group in source_groups.items():
        anchor = group[0]
        try:
            parsed = parse_text_line(
                anchor.raw_text,
                sheet_name=anchor.sheet_name or "图片自动识别",
                quote_date=anchor.quote_date,
                cell_address=anchor.cell_address,
                source_line=anchor.source_line,
            )
            parsed_counts[key] = len(parsed) if parsed else None
        except Exception:
            parsed_counts[key] = None

    history_by_key: dict[tuple[Any, ...], list[PriceQuote]] = defaultdict(list)
    brands = {item.brand for item in candidates if item.brand}
    if candidates and brands:
        latest_candidate_date = max(item.quote_date for item in candidates)
        previous_quotes = db.scalars(
            select(PriceQuote)
            .where(
                PriceQuote.brand.in_(brands),
                PriceQuote.quote_date < latest_candidate_date,
                PriceQuote.price_status == PriceStatus.QUOTED,
                PriceQuote.price.is_not(None),
            )
            .order_by(PriceQuote.quote_date.desc(), PriceQuote.id.desc())
        ).all()
        for quote in previous_quotes:
            history_by_key[_history_key(quote)].append(quote)

    risks: list[ReviewBatchDiagnosisItem] = []
    safe_candidate_ids: list[int] = []
    issue_counts: Counter[str] = Counter()
    warning_count = 0
    danger_count = 0

    for candidate in candidates:
        issues: list[str] = []
        if (
            not candidate.model.strip()
            or not candidate.model_normalized.strip()
            or candidate.brand == "Other"
            or (candidate.price_status == PriceStatus.QUOTED and candidate.price is None)
        ):
            issues.append("信息不完整")
        if candidate.confidence < 0.75:
            issues.append("低置信度")
        elif candidate.confidence < AUTO_APPROVE_CONFIDENCE:
            issues.append("置信度未达自动通过标准")
        if duplicate_counts[_identity_key(candidate)] > 1:
            issues.append("重复报价")

        previous = next(
            (
                quote
                for quote in history_by_key.get(_history_key(candidate), [])
                if quote.quote_date < candidate.quote_date
            ),
            None,
        )
        if (
            previous
            and previous.price is not None
            and candidate.price_status == PriceStatus.QUOTED
            and candidate.price is not None
            and abs(Decimal(candidate.price) - Decimal(previous.price)) >= ABNORMAL_CHANGE_THRESHOLD
        ):
            issues.append("价格异常波动")

        source_key = _source_key(candidate)
        group = source_groups[source_key]
        parsed_count = parsed_counts[source_key]
        if parsed_count is not None and parsed_count != len(group):
            issues.append("来源行拆分不一致")

        sibling_models = [item.model for item in group if item.id != candidate.id and item.model]
        if sibling_models:
            majority_model, majority_count = Counter(sibling_models).most_common(1)[0]
            compact_raw = "".join(candidate.raw_text.lower().split())
            compact_majority = "".join(majority_model.lower().split())
            if (
                majority_count >= max(1, len(sibling_models) // 2 + len(sibling_models) % 2)
                and normalize_model(majority_model) != candidate.model_normalized
                and compact_majority in compact_raw
            ):
                issues.append("型号可能不一致")

        issues = list(dict.fromkeys(issues))
        if not issues:
            if candidate.review_status == ReviewStatus.PENDING:
                safe_candidate_ids.append(candidate.id)
            continue

        issue_counts.update(issues)
        severity = "danger" if {"重复报价", "价格异常波动"}.intersection(issues) else "warning"
        if severity == "danger":
            danger_count += 1
        else:
            warning_count += 1
        source_unit = candidate.cell_address or (
            f"第 {candidate.source_line} 行" if candidate.source_line else f"记录 {candidate.id}"
        )
        risks.append(
            ReviewBatchDiagnosisItem(
                candidate=CandidateRead.model_validate(candidate),
                severity=severity,
                issue_types=issues,
                summary=_batch_risk_suggestion(issues),
                source_label=f"{candidate.sheet_name or '未识别板块'} · {source_unit}",
            )
        )

    risks.sort(key=lambda item: (0 if item.severity == "danger" else 1, item.candidate.id))
    return BatchDiagnosisBundle(
        batch=batch,
        signature=_batch_signature(batch, candidates),
        candidates=candidates,
        safe_candidate_ids=safe_candidate_ids,
        risks=risks,
        issue_counts=issue_counts,
        warning_count=warning_count,
        danger_count=danger_count,
    )


def _review_tool_payload(db: Session, candidate: QuoteCandidate, name: str) -> dict[str, Any]:
    if name == "inspect_source":
        return {
            "source_type": candidate.batch.source_type.value,
            "sheet_name": candidate.sheet_name,
            "cell_address": candidate.cell_address,
            "source_line": candidate.source_line,
            "raw_text": candidate.raw_text,
        }
    if name == "compare_history":
        previous = _previous_quote(db, candidate)
        return {
            "found": previous is not None,
            "previous_date": previous.quote_date if previous else None,
            "previous_price": previous.price if previous else None,
            "current_price": candidate.price,
            "difference": (
                Decimal(candidate.price) - Decimal(previous.price)
                if previous and previous.price is not None and candidate.price is not None
                else None
            ),
        }
    if name == "check_duplicates":
        duplicates = _duplicates(db, candidate)
        return {
            "count": len(duplicates),
            "candidate_ids": [item.id for item in duplicates[:10]],
        }
    if name in {"check_source_structure", "reparse_source"}:
        group = _source_group(db, candidate)
        try:
            parsed = parse_text_line(
                candidate.raw_text,
                sheet_name=candidate.sheet_name or "图片自动识别",
                quote_date=candidate.quote_date,
                cell_address=candidate.cell_address,
                source_line=candidate.source_line,
            )
        except Exception:
            parsed = []
        if name == "check_source_structure":
            return {
                "current_count": len(group),
                "parsed_count": len(parsed),
                "current_models": list(dict.fromkeys(item.model for item in group if item.model)),
                "parsed_models": list(dict.fromkeys(item.model for item in parsed if item.model)),
            }
        return {
            "parsed_count": len(parsed),
            "parsed_items": [
                {
                    "brand": item.brand,
                    "model": item.model,
                    "storage": item.storage,
                    "color": item.color,
                    "variant": item.variant,
                    "price_status": item.price_status.value,
                    "price": item.price,
                }
                for item in parsed[:20]
            ],
        }
    return {"error": "不支持的复核工具"}


def _review_tool_detail(name: str, payload: dict[str, Any]) -> str:
    if name == "inspect_source":
        unit = payload.get("cell_address") or payload.get("source_line") or "当前记录"
        return f"已读取 {payload.get('sheet_name') or '未识别板块'} · {unit} 的来源原文。"
    if name == "compare_history":
        if not payload.get("found"):
            return "没有找到身份完全匹配的上一期已发布报价。"
        return f"已取得上一期价格并计算差额 {payload.get('difference')} 元。"
    if name == "check_duplicates":
        return f"同批次找到 {payload.get('count', 0)} 条完全相同记录。"
    if name == "check_source_structure":
        return f"当前来源包含 {payload.get('current_count', 0)} 条记录，重新解析得到 {payload.get('parsed_count', 0)} 条。"
    if name == "reparse_source":
        return f"重新解析来源原文得到 {payload.get('parsed_count', 0)} 条候选报价。"
    return "工具执行完成。"


def _run_review_tool_agent(
    db: Session,
    candidate: QuoteCandidate,
) -> tuple[list[str], list[ReviewAgentStep], bool]:
    candidate_facts = {
        "candidate_id": candidate.id,
        "source_type": candidate.batch.source_type.value,
        "brand": candidate.brand,
        "model": candidate.model,
        "storage": candidate.storage,
        "color": candidate.color,
        "variant": candidate.variant,
        "price_status": candidate.price_status.value,
        "price": candidate.price,
        "quote_date": candidate.quote_date,
        "recognition_confidence": candidate.confidence,
    }
    selected: list[str] = []
    model_selected_tools = False
    try:
        response = _ollama_chat(
            {
                "model": settings.ollama_model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "你是3C报价复核诊断智能体的规划器。只选择需要执行的只读工具，不作最终结论。"
                            "必须选择inspect_source、check_duplicates、check_source_structure；有明确价格时选择compare_history；"
                            "低置信度或品牌不确定时选择reparse_source。不得输出工具列表之外的名称。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"为这条候选报价制定检查计划：{json.dumps(candidate_facts, ensure_ascii=False, default=_json_value)}",
                    },
                ],
                "format": {
                    "type": "object",
                    "properties": {
                        "checks": {
                            "type": "array",
                            "items": {"type": "string", "enum": list(REVIEW_TOOL_LABELS)},
                            "maxItems": 5,
                        },
                        "reason": {"type": "string"},
                    },
                    "required": ["checks", "reason"],
                },
                "stream": False,
                "keep_alive": "10m",
                "options": {"temperature": 0, "num_predict": 100},
            }
        )
        result = json.loads(str((response.get("message") or {}).get("content") or ""))
        selected = list(
            dict.fromkeys(
                str(name) for name in result.get("checks", []) if str(name) in REVIEW_TOOL_LABELS
            )
        )
        model_selected_tools = bool(selected)
    except (AgentUnavailableError, json.JSONDecodeError, TypeError, AttributeError):
        selected = []

    required = ["inspect_source", "check_duplicates", "check_source_structure"]
    if candidate.price_status == PriceStatus.QUOTED and candidate.price is not None:
        required.append("compare_history")
    if candidate.confidence < 0.75 or candidate.brand == "Other":
        required.append("reparse_source")
    executed = [*selected, *(name for name in required if name not in selected)]
    tool_steps: list[ReviewAgentStep] = []
    for name in executed:
        payload = _review_tool_payload(db, candidate, name)
        tool_steps.append(
            ReviewAgentStep(
                order=0,
                phase="tool",
                title=REVIEW_TOOL_LABELS[name],
                detail=_review_tool_detail(name, payload),
                status="completed" if name in selected else "fallback",
                tool=name,
            )
        )

    planning = ReviewAgentStep(
        order=1,
        phase="planning",
        title="制定审核计划",
        detail=(
            f"Qwen 根据记录特征选择了 {len(executed)} 个证据工具。"
            if model_selected_tools
            else f"本地模型未完成工具规划，系统按安全基线执行了 {len(executed)} 个检查工具。"
        ),
        status="completed" if model_selected_tools else "fallback",
    )
    steps = [planning, *tool_steps]
    for order, step in enumerate(steps, start=1):
        step.order = order
    return executed, steps, model_selected_tools


def _collect_diagnosis(
    db: Session,
    candidate_id: int,
    enabled_tools: set[str] | None = None,
) -> DiagnosisBundle:
    candidate = db.get(QuoteCandidate, candidate_id)
    if not candidate:
        raise ReviewCandidateNotFoundError("候选记录不存在")

    enabled = set(REVIEW_TOOL_LABELS) if enabled_tools is None else enabled_tools
    needs_structure = bool({"check_source_structure", "reparse_source"}.intersection(enabled))
    group = _source_group(db, candidate) if needs_structure else [candidate]
    previous = _previous_quote(db, candidate) if "compare_history" in enabled else None
    duplicates = _duplicates(db, candidate) if "check_duplicates" in enabled else []
    evidence: list[ReviewDiagnosisEvidence] = []
    issues: list[str] = []
    recommendations: list[str] = []
    changes: list[ReviewDiagnosisChange] = []
    severity = "normal"

    source_unit = candidate.cell_address or (f"第 {candidate.source_line} 行" if candidate.source_line else f"记录 {candidate.id}")
    source_label = f"{candidate.sheet_name or '未识别板块'} · {source_unit}"
    evidence.append(
        ReviewDiagnosisEvidence(
            category="source",
            title="来源原文",
            detail=candidate.raw_text,
        )
    )

    if (
        not candidate.model.strip()
        or not candidate.model_normalized.strip()
        or candidate.brand == "Other"
        or (candidate.price_status == PriceStatus.QUOTED and candidate.price is None)
    ):
        _append_unique(issues, "信息不完整")
        severity = "warning"
        evidence.append(
            ReviewDiagnosisEvidence(
                category="structure",
                title="关键字段不完整",
                detail="品牌、型号或明确报价所需的价格字段存在缺失，请对照来源补齐。",
                severity="warning",
            )
        )
        recommendations.append("先补齐品牌、型号或价格等关键字段，再确认复核结果。")

    if candidate.confidence < 0.75:
        _append_unique(issues, "低置信度")
        severity = "warning"
        evidence.append(
            ReviewDiagnosisEvidence(
                category="confidence",
                title="识别置信度较低",
                detail=f"原始识别置信度为 {round(candidate.confidence * 100)}%，建议对照来源检查字段。",
                severity="warning",
            )
        )
        recommendations.append("先对照原图或 Excel 单元格核对型号、容量、颜色和价格。")

    if duplicates:
        _append_unique(issues, "重复报价")
        severity = "danger"
        duplicate_ids = "、".join(str(item.id) for item in duplicates[:5])
        evidence.append(
            ReviewDiagnosisEvidence(
                category="duplicate",
                title="同批次存在完全相同报价",
                detail=f"发现 {len(duplicates)} 条相同记录，候选编号：{duplicate_ids}。",
                severity="danger",
            )
        )
        recommendations.append("确认重复来源后只保留一条，避免同日报价重复发布。")
        if any(item.id < candidate.id for item in duplicates):
            changes.append(
                _change(
                    candidate,
                    "review_status",
                    ReviewStatus.REJECTED,
                    "同批次已有更早生成的完全相同记录，建议拒绝当前重复项。",
                )
            )

    if (
        previous
        and previous.price is not None
        and candidate.price_status == PriceStatus.QUOTED
        and candidate.price is not None
    ):
        difference = Decimal(candidate.price) - Decimal(previous.price)
        if abs(difference) >= ABNORMAL_CHANGE_THRESHOLD:
            _append_unique(issues, "价格异常波动")
            severity = "danger"
            evidence.append(
                ReviewDiagnosisEvidence(
                    category="history",
                    title="与上一期价格差距较大",
                    detail=(
                        f"上一期 {previous.quote_date} 为 {previous.price} 元，当前为 {candidate.price} 元，"
                        f"相差 {difference:+} 元。"
                    ),
                    severity="danger",
                )
            )
            recommendations.append("结合来源原文确认当前价格；历史价格只作为证据，不会自动覆盖本期报价。")

    parsed_items = []
    if needs_structure:
        try:
            parsed_items = parse_text_line(
                candidate.raw_text,
                sheet_name=candidate.sheet_name or "图片自动识别",
                quote_date=candidate.quote_date,
                cell_address=candidate.cell_address,
                source_line=candidate.source_line,
            )
        except Exception:
            parsed_items = []

    if "check_source_structure" in enabled and parsed_items and len(parsed_items) != len(group):
        _append_unique(issues, "来源行拆分不一致")
        if severity == "normal":
            severity = "warning"
        evidence.append(
            ReviewDiagnosisEvidence(
                category="structure",
                title="来源原文与当前拆分数量不同",
                detail=f"按当前解析规则可得到 {len(parsed_items)} 条，复核区现有 {len(group)} 条。",
                severity="warning",
            )
        )
        recommendations.append("打开整行编辑，补齐或删除颜色报价后再保存。")

    sibling_models = [
        item.model
        for item in group
        if "check_source_structure" in enabled and item.id != candidate.id and item.model
    ]
    if sibling_models:
        majority_model, majority_count = Counter(sibling_models).most_common(1)[0]
        compact_raw = "".join(candidate.raw_text.lower().split())
        compact_majority = "".join(majority_model.lower().split())
        if (
            majority_count >= max(1, len(sibling_models) // 2 + len(sibling_models) % 2)
            and normalize_model(majority_model) != candidate.model_normalized
            and compact_majority in compact_raw
        ):
            _append_unique(issues, "型号可能不一致")
            if severity == "normal":
                severity = "warning"
            evidence.append(
                ReviewDiagnosisEvidence(
                    category="structure",
                    title="同一来源行的型号不一致",
                    detail=f"同一行其他 {majority_count} 条记录使用型号“{majority_model}”，且原文中包含该型号。",
                    severity="warning",
                )
            )
            changes.append(_change(candidate, "model", majority_model, "采用同一来源行且原文中存在的多数型号。"))
            recommendations.append("核对 Pro、Max、Turbo 等后缀是否在识别时丢失。")

    if "reparse_source" in enabled and parsed_items and candidate.confidence < 0.75:
        source_match = next(
            (
                item
                for item in parsed_items
                if item.storage == candidate.storage and item.color == candidate.color
            ),
            None,
        )
        if source_match:
            if source_match.model and source_match.model_normalized != candidate.model_normalized:
                if not any(item.field == "model" for item in changes):
                    changes.append(_change(candidate, "model", source_match.model, "按当前来源原文重新解析得到该型号。"))
            if source_match.price_status == PriceStatus.QUOTED and source_match.price != candidate.price:
                if candidate.price_status != PriceStatus.QUOTED:
                    changes.append(_change(candidate, "price_status", PriceStatus.QUOTED, "来源原文包含明确价格。"))
                changes.append(_change(candidate, "price", source_match.price, "按当前来源原文重新解析得到该价格。"))

    if not issues:
        recommendations.append("未发现规则层面的明显异常，仍建议对照来源完成最终确认。")

    return DiagnosisBundle(
        candidate=candidate,
        signature=_candidate_signature(candidate),
        severity=severity,
        issue_types=issues,
        evidence=evidence[:8],
        recommendations=list(dict.fromkeys(recommendations))[:3],
        proposed_changes=list({item.field: item for item in changes}.values()),
        source_label=source_label,
    )


def _fallback_summary(bundle: DiagnosisBundle) -> str:
    if not bundle.issue_types:
        return "规则检查未发现明显异常，可以对照来源后标记为无问题。"
    return f"发现{len(bundle.issue_types)}类疑点：{'、'.join(bundle.issue_types)}。请根据证据完成最终确认。"


def _model_output_is_safe(summary: str, recommendations: list[str], facts: dict[str, Any]) -> bool:
    output = " ".join([summary, *recommendations])
    unsupported_certainty = ("识别准确", "识别正确", "确认无误", "可以直接发布", "无需核对", "自动修改")
    if any(term in output for term in unsupported_certainty):
        return False
    fact_text = json.dumps(facts, ensure_ascii=False, default=_json_value)
    allowed_numbers = set(re.findall(r"\d+(?:\.\d+)?", fact_text))
    output_numbers = set(re.findall(r"\d+(?:\.\d+)?", output))
    return output_numbers.issubset(allowed_numbers)


def _model_explanation(bundle: DiagnosisBundle) -> tuple[str, list[str], bool]:
    fallback_summary = _fallback_summary(bundle)
    fallback_recommendations = bundle.recommendations
    facts = {
        "candidate": {
            "brand": bundle.candidate.brand,
            "model": bundle.candidate.model,
            "storage": bundle.candidate.storage,
            "color": bundle.candidate.color,
            "price_status": bundle.candidate.price_status.value,
            "price": bundle.candidate.price,
            "quote_date": bundle.candidate.quote_date,
            "recognition_confidence": bundle.candidate.confidence,
        },
        "issue_types": bundle.issue_types,
        "evidence": [item.model_dump() for item in bundle.evidence],
        "rule_recommendations": bundle.recommendations,
    }
    try:
        response = _ollama_chat(
            {
                "model": settings.ollama_model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "你是3C报价复核诊断智能体。只解释给定的规则检查事实，不得新增数字、价格或修改建议。"
                            "不得声称任何字段准确、正确或确认无误。summary不超过90字，recommendations最多3条。"
                            "只能改写rule_recommendations；没有证据时明确建议人工核对。"
                        ),
                    },
                    {"role": "user", "content": json.dumps(facts, ensure_ascii=False, default=_json_value)},
                ],
                "format": {
                    "type": "object",
                    "properties": {
                        "summary": {"type": "string"},
                        "recommendations": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
                    },
                    "required": ["summary", "recommendations"],
                },
                "stream": False,
                "keep_alive": "10m",
                "options": {"temperature": 0, "num_predict": 180},
            }
        )
        result = json.loads(str((response.get("message") or {}).get("content") or ""))
        summary = str(result.get("summary") or "").strip()
        recommendations = [str(item).strip() for item in result.get("recommendations", []) if str(item).strip()]
        if summary and _model_output_is_safe(summary, recommendations, facts):
            return summary, recommendations[:3] or fallback_recommendations, True
    except (AgentUnavailableError, json.JSONDecodeError, TypeError, AttributeError):
        pass
    return fallback_summary, fallback_recommendations, False


def diagnose_review_candidate(db: Session, candidate_id: int) -> ReviewDiagnosisResponse:
    candidate = db.get(QuoteCandidate, candidate_id)
    if not candidate:
        raise ReviewCandidateNotFoundError("候选记录不存在")
    tools_used, workflow_steps, model_selected_tools = _run_review_tool_agent(db, candidate)
    bundle = _collect_diagnosis(db, candidate_id, set(tools_used))
    needs_model_reasoning = bundle.severity == "danger" or len(bundle.issue_types) >= 2
    if needs_model_reasoning:
        summary, recommendations, generated_by_model = _model_explanation(bundle)
    else:
        summary, recommendations, generated_by_model = _fallback_summary(bundle), bundle.recommendations, False
    workflow_steps.append(
        ReviewAgentStep(
            order=len(workflow_steps) + 1,
            phase="reasoning",
            title="综合证据形成结论",
            detail=(
                "Qwen 仅根据工具返回的事实生成诊断说明，字段修改建议仍由确定性规则产生。"
                if generated_by_model
                else (
                    "单一风险已由确定性规则直接形成结论，无需再次等待模型生成说明。"
                    if not needs_model_reasoning
                    else "模型说明未通过安全校验，已使用确定性规则结论。"
                )
            ),
            status="completed" if generated_by_model or not needs_model_reasoning else "fallback",
        )
    )
    workflow_steps.append(
        ReviewAgentStep(
            order=len(workflow_steps) + 1,
            phase="verification",
            title="安全校验",
            detail="已校验结论中的数字来自工具证据；任何修改都需要人工确认后才能执行。",
        )
    )
    candidate = bundle.candidate
    return ReviewDiagnosisResponse(
        agent_run_id=str(uuid4()),
        candidate_id=candidate.id,
        candidate_signature=bundle.signature,
        severity=bundle.severity,
        issue_types=bundle.issue_types,
        summary=summary,
        evidence=bundle.evidence,
        recommendations=recommendations,
        proposed_changes=bundle.proposed_changes,
        generated_by_model=generated_by_model,
        model=settings.ollama_model,
        source_type=candidate.batch.source_type,
        source_label=bundle.source_label,
        recognition_confidence=candidate.confidence,
        verification_status=(
            "human_confirmed"
            if candidate.review_status != ReviewStatus.PENDING
            or (candidate.review_note or "").startswith("[智能诊断确认]")
            else "unverified"
        ),
        agent_mode="tool_calling" if model_selected_tools else "rule_fallback",
        tools_used=tools_used,
        workflow_steps=workflow_steps,
    )


def diagnose_review_batch(db: Session, batch_id: int) -> ReviewBatchDiagnosisResponse:
    bundle = _scan_batch(db, batch_id)
    auto_approved_count = sum(
        1
        for candidate in bundle.candidates
        if candidate.review_status == ReviewStatus.APPROVED
        and (candidate.review_note or "").startswith(AUTO_APPROVAL_NOTE_PREFIX)
    )
    return ReviewBatchDiagnosisResponse(
        batch_id=batch_id,
        batch_signature=bundle.signature,
        scanned_count=len(bundle.candidates),
        safe_count=len(bundle.candidates) - len(bundle.risks),
        pending_safe_count=len(bundle.safe_candidate_ids),
        auto_approved_count=auto_approved_count,
        warning_count=bundle.warning_count,
        danger_count=bundle.danger_count,
        issue_counts=dict(bundle.issue_counts.most_common()),
        risks=bundle.risks,
    )


def approve_safe_review_batch(
    db: Session,
    batch_id: int,
    request: ReviewBatchApproveSafeRequest,
) -> ReviewBatchApproveSafeResponse:
    bundle = _scan_batch(db, batch_id)
    if bundle.batch.status == BatchStatus.COMMITTED:
        raise ReviewDiagnosisApplyError("已发布批次不能执行批量审核，请先撤回到复核")
    if request.batch_signature != bundle.signature:
        raise ReviewDiagnosisConflictError("批次数据已发生变化，请重新执行一键智能审核")

    safe_ids = set(bundle.safe_candidate_ids)
    approved_count = 0
    agent_run_id = str(uuid4())
    for candidate in bundle.candidates:
        if candidate.id not in safe_ids or candidate.review_status != ReviewStatus.PENDING:
            continue
        before_data = candidate_snapshot(candidate)
        candidate.review_status = ReviewStatus.APPROVED
        old_note = (candidate.review_note or "").strip()
        candidate.review_note = (
            f"{AUTO_APPROVAL_NOTE_PREFIX} 置信度 {candidate.confidence:.0%}，"
            "字段完整，且未发现重复、异常波动或来源结构问题"
        )
        if old_note:
            candidate.review_note += f"；{old_note}"
        candidate.review_note = candidate.review_note[:500]
        add_audit_log(
            db,
            action_type=AUTO_APPROVE,
            operator_type=AGENT,
            before_data=before_data,
            after_data=candidate_snapshot(candidate),
            batch_id=candidate.batch_id,
            candidate_id=candidate.id,
            reason=candidate.review_note,
            agent_run_id=agent_run_id,
        )
        approved_count += 1

    db.commit()
    remaining_pending = sum(
        1 for candidate in bundle.candidates if candidate.review_status == ReviewStatus.PENDING
    )
    return ReviewBatchApproveSafeResponse(
        batch_id=batch_id,
        approved_count=approved_count,
        remaining_pending=remaining_pending,
        agent_run_id=agent_run_id,
    )


def revoke_auto_approval(db: Session, candidate_id: int) -> QuoteCandidate:
    candidate = db.get(QuoteCandidate, candidate_id)
    if not candidate:
        raise ReviewCandidateNotFoundError("候选记录不存在")
    if candidate.batch.status == BatchStatus.COMMITTED or candidate.quote is not None:
        raise ReviewDiagnosisApplyError("已发布记录不能撤销自动通过，请先将批次撤回到复核")
    note = (candidate.review_note or "").strip()
    if candidate.review_status != ReviewStatus.APPROVED or not note.startswith(AUTO_APPROVAL_NOTE_PREFIX):
        raise ReviewDiagnosisApplyError("这条记录不是智能体自动通过的数据")
    before_data = candidate_snapshot(candidate)
    candidate.review_status = ReviewStatus.PENDING
    reason = note[len(AUTO_APPROVAL_NOTE_PREFIX):].strip()
    candidate.review_note = f"[已撤销自动审核] {reason}"[:500]
    add_audit_log(
        db,
        action_type=REVOKE_AUTO_APPROVE,
        operator_type=HUMAN,
        before_data=before_data,
        after_data=candidate_snapshot(candidate),
        batch_id=candidate.batch_id,
        candidate_id=candidate.id,
        reason="人工发现需要重新检查，撤销智能体自动通过状态",
    )
    db.commit()
    db.refresh(candidate)
    return candidate


def _coerce_change_value(field: str, value: Any) -> Any:
    if field == "price":
        return Decimal(str(value)) if value is not None else None
    if field == "price_status":
        return PriceStatus(str(value))
    if field == "review_status":
        return ReviewStatus(str(value))
    return None if value is None else str(value)


def apply_review_diagnosis(
    db: Session,
    candidate_id: int,
    request: ReviewDiagnosisApplyRequest,
) -> ReviewDiagnosisApplyResponse:
    bundle = _collect_diagnosis(db, candidate_id)
    candidate = bundle.candidate
    if candidate.batch.status == BatchStatus.COMMITTED or candidate.quote is not None:
        raise ReviewDiagnosisApplyError("已发布记录不能应用诊断修改，请先撤回到复核")
    if request.candidate_signature != bundle.signature:
        raise ReviewDiagnosisConflictError("记录已发生变化，请重新运行智能诊断")

    before_data = candidate_snapshot(candidate)
    applied_fields: list[str] = []
    if request.decision == "mark_no_issue":
        if request.fields:
            raise ReviewDiagnosisApplyError("标记无问题时不能同时应用字段修改")
        candidate.review_status = ReviewStatus.APPROVED
    else:
        available = {item.field: item for item in bundle.proposed_changes}
        requested_fields = list(dict.fromkeys(request.fields))
        if not requested_fields:
            raise ReviewDiagnosisApplyError("请至少选择一项诊断建议")
        if any(field not in available for field in requested_fields):
            raise ReviewDiagnosisConflictError("诊断建议已经变化，请重新运行智能诊断")
        payload = {
            field: _coerce_change_value(field, available[field].suggested_value)
            for field in requested_fields
        }
        update_candidate(candidate, payload)
        applied_fields = [FIELD_LABELS[field] for field in requested_fields]
        if "review_status" not in payload:
            candidate.review_status = ReviewStatus.APPROVED

    action = "标记无问题" if request.decision == "mark_no_issue" else f"采用建议：{'、'.join(applied_fields)}"
    old_note = (candidate.review_note or "").strip()
    candidate.review_note = f"[智能诊断确认] {action}" + (f"；{old_note}" if old_note else "")
    candidate.review_note = candidate.review_note[:500]
    add_audit_log(
        db,
        action_type=MARK_NO_ISSUE if request.decision == "mark_no_issue" else AGENT_SUGGESTION_APPLY,
        operator_type=HUMAN,
        before_data=before_data,
        after_data=candidate_snapshot(candidate),
        batch_id=candidate.batch_id,
        candidate_id=candidate.id,
        reason=action,
        agent_run_id=request.agent_run_id,
        model_name=settings.ollama_model,
    )
    db.commit()
    db.refresh(candidate)
    rechecked = _collect_diagnosis(db, candidate.id)
    if not rechecked.issue_types:
        verification_summary = "修改已执行，自动复查未发现剩余规则异常。"
    elif candidate.review_status == ReviewStatus.REJECTED:
        verification_summary = "记录已拒绝，不会进入正式报价；自动复查保留原风险作为审计依据。"
    elif request.decision == "mark_no_issue":
        verification_summary = "已记录人工确认；自动复查仍保留原始识别风险和置信度，不会篡改识别事实。"
    else:
        verification_summary = f"修改已执行，自动复查仍发现：{'、'.join(rechecked.issue_types)}。"
    return ReviewDiagnosisApplyResponse(
        candidate=candidate,
        applied_fields=applied_fields,
        remaining_issue_types=rechecked.issue_types,
        verification_summary=verification_summary,
    )
