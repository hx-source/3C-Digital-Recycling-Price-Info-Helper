from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.entities import PriceQuote, PriceStatus
from app.schemas.quotes import AgentChatRequest, AgentSource, ImportAgentSummaryRequest
from app.services.quote_service import dashboard_summary, price_changes


SYSTEM_PROMPT = """你是“回收雷达”的行情问答助手，服务于 3C 数码回收报价人员。
所有价格、涨跌和日期都必须以工具返回的数据为准，不得猜测或编造。
遇到需要实时行情、型号报价、品牌表现、异常波动或价格来源的问题，必须先调用工具。
工具没有返回数据时，直接说明“当前已发布数据中未找到”，并提示用户补充型号、容量、颜色或先完成报价发布。
用简洁、专业的中文回答；金额以“元”说明。排行或异常清单最多列出 5 条。不要执行、建议或暗示修改数据库，系统只提供只读查询。"""


class AgentUnavailableError(RuntimeError):
    pass


@dataclass(slots=True)
class ToolResponse:
    payload: dict[str, Any]
    sources: list[AgentSource]


TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_market_overview",
            "description": "获取当前已发布报价的整体行情概览，包括最新报价日、报价数量、上涨和下跌数量。适用于询问今日整体行情、市场概况。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_latest_quotes",
            "description": "查询已发布的具体报价。适用于询问某个型号、容量、颜色、品牌或品类的当前价格。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "型号、容量、颜色或关键词；不确定时传空字符串"},
                    "brand": {"type": "string", "description": "品牌名称；不确定时传空字符串"},
                    "limit": {"type": "integer", "description": "返回数量，1 到 5，默认 5"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_price_changes",
            "description": "查询已发布报价的最新涨跌。适用于询问某品牌、某型号的涨跌，或上涨最多、下跌最多的型号。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "型号、容量或颜色关键词；不确定时传空字符串"},
                    "brand": {"type": "string", "description": "品牌名称；不确定时传空字符串"},
                    "direction": {"type": "string", "enum": ["all", "up", "down"], "description": "上涨用 up，下跌用 down，其他用 all"},
                    "limit": {"type": "integer", "description": "返回数量，1 到 5，默认 5"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_abnormal_changes",
            "description": "查询涨跌绝对值达到 500 元及以上、需要人工复核的异常波动报价。",
            "parameters": {
                "type": "object",
                "properties": {
                    "brand": {"type": "string", "description": "品牌名称；不确定时传空字符串"},
                    "limit": {"type": "integer", "description": "返回数量，1 到 5，默认 5"},
                },
            },
        },
    },
]


def _limit(value: Any, default: int = 5) -> int:
    try:
        return max(1, min(int(value), 5))
    except (TypeError, ValueError):
        return default


def _text(value: Any) -> str:
    return str(value or "").strip()


def _quote_label(row: PriceQuote) -> str:
    return " ".join(part for part in (row.brand, row.model, row.storage, row.color, row.variant) if part)


def _quote_source(row: PriceQuote) -> AgentSource:
    price = f"{row.price} 元" if row.price is not None else "暂无明确价格"
    return AgentSource(
        label=_quote_label(row),
        detail=f"{row.quote_date} · {price} · 来源：{row.source_name}",
    )


def _search_latest_quotes(db: Session, arguments: dict[str, Any]) -> ToolResponse:
    query = _text(arguments.get("query"))
    brand = _text(arguments.get("brand"))
    filters = [PriceQuote.price_status == PriceStatus.QUOTED, PriceQuote.price.is_not(None)]
    if brand:
        filters.append(PriceQuote.brand.ilike(f"%{brand}%"))
    if query:
        pattern = f"%{query}%"
        filters.append(
            or_(
                PriceQuote.brand.ilike(pattern),
                PriceQuote.model.ilike(pattern),
                PriceQuote.storage.ilike(pattern),
                PriceQuote.color.ilike(pattern),
                PriceQuote.variant.ilike(pattern),
            )
        )
    rows = db.scalars(
        select(PriceQuote)
        .where(*filters)
        .order_by(PriceQuote.quote_date.desc(), PriceQuote.id.desc())
        .limit(_limit(arguments.get("limit")))
    ).all()
    return ToolResponse(
        payload={
            "count": len(rows),
            "quotes": [
                {
                    "brand": row.brand,
                    "model": row.model,
                    "storage": row.storage,
                    "color": row.color,
                    "variant": row.variant,
                    "quote_date": row.quote_date,
                    "price": row.price,
                    "source_name": row.source_name,
                }
                for row in rows
            ],
        },
        sources=[_quote_source(row) for row in rows],
    )


def _change_source(item: Any) -> AgentSource:
    label = " ".join(part for part in (item.brand, item.model, item.storage, item.color, item.variant) if part)
    change = f"{item.change_amount:+} 元" if item.change_amount is not None else "暂无可对比上期"
    return AgentSource(
        label=label,
        detail=f"{item.current_date} · 当前 {item.current_price} 元 · 涨跌 {change}",
    )


def _get_price_changes(db: Session, arguments: dict[str, Any], *, abnormal_only: bool = False) -> ToolResponse:
    query = _text(arguments.get("query"))
    brand = _text(arguments.get("brand"))
    direction = _text(arguments.get("direction")) or "all"
    rows = price_changes(db, brand=brand or None, search=query or None, limit=5000)
    rows = [item for item in rows if item.change_amount is not None]
    if abnormal_only:
        rows = [item for item in rows if item.requires_review]
    elif direction == "up":
        rows = [item for item in rows if item.change_amount and item.change_amount > 0]
    elif direction == "down":
        rows = [item for item in rows if item.change_amount and item.change_amount < 0]
    if direction == "up":
        rows.sort(key=lambda item: item.change_amount or Decimal(0), reverse=True)
    elif direction == "down":
        rows.sort(key=lambda item: item.change_amount or Decimal(0))
    else:
        rows.sort(key=lambda item: abs(item.change_amount or Decimal(0)), reverse=True)
    rows = rows[:_limit(arguments.get("limit"))]
    return ToolResponse(
        payload={
            "count": len(rows),
            "changes": [
                {
                    "brand": item.brand,
                    "model": item.model,
                    "storage": item.storage,
                    "color": item.color,
                    "current_date": item.current_date,
                    "current_price": item.current_price,
                    "previous_date": item.previous_date,
                    "previous_price": item.previous_price,
                    "change_amount": item.change_amount,
                    "change_percent": item.change_percent,
                    "requires_review": item.requires_review,
                }
                for item in rows
            ],
        },
        sources=[_change_source(item) for item in rows],
    )


def _get_market_overview(db: Session) -> ToolResponse:
    summary = dashboard_summary(db)
    return ToolResponse(
        payload={
            "latest_quote_date": summary.latest_quote_date,
            "published_quotes": summary.published_quotes,
            "pending_candidates": summary.pending_candidates,
            "today_increases": summary.today_increases,
            "today_decreases": summary.today_decreases,
            "today_unchanged": summary.today_unchanged,
        },
        sources=[],
    )


def _execute_tool(db: Session, name: str, arguments: dict[str, Any]) -> ToolResponse:
    if name == "get_market_overview":
        return _get_market_overview(db)
    if name == "search_latest_quotes":
        return _search_latest_quotes(db, arguments)
    if name == "get_price_changes":
        return _get_price_changes(db, arguments)
    if name == "get_abnormal_changes":
        return _get_price_changes(db, arguments, abnormal_only=True)
    return ToolResponse(payload={"error": "不支持的查询工具"}, sources=[])


def _ollama_chat(payload: dict[str, Any]) -> dict[str, Any]:
    request = Request(
        f"{settings.ollama_base_url.rstrip('/')}/api/chat",
        data=json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=settings.ollama_timeout_seconds) as response:  # noqa: S310 - configured local endpoint
            return json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, json.JSONDecodeError) as error:
        raise AgentUnavailableError("本机 Ollama 未启动或模型暂时不可用") from error


def _arguments_with_memory(arguments: dict[str, Any], memory: dict[str, Any]) -> dict[str, Any]:
    resolved = dict(arguments)
    if not _text(resolved.get("brand")) and memory.get("brand"):
        resolved["brand"] = memory["brand"]
    if not _text(resolved.get("query")):
        parts = [memory.get("model"), memory.get("storage"), memory.get("color")]
        resolved["query"] = " ".join(_text(part) for part in parts if _text(part))
    return resolved


def _updated_memory(memory: dict[str, Any], question: str, tool_arguments: list[dict[str, Any]]) -> dict[str, Any]:
    output = dict(memory)
    for arguments in tool_arguments:
        brand = _text(arguments.get("brand"))
        query = _text(arguments.get("query"))
        if brand:
            output["brand"] = brand
        if query:
            storage = re.search(r"\b\d{1,2}\s*\+\s*(?:\d{2,4}|1\s*[Tt])\b", query, re.I)
            if storage:
                output["storage"] = re.sub(r"\s+", "", storage.group(0)).upper()
            model = re.sub(r"\b\d{1,2}\s*\+\s*(?:\d{2,4}|1\s*[Tt])\b", "", query, flags=re.I).strip()
            if model:
                output["model"] = model
    for brand in ("华为", "荣耀", "苹果", "小米", "红米", "OPPO", "vivo", "一加", "真我", "三星"):
        if brand.lower() in question.lower():
            output["brand"] = brand
            break
    output["last_question"] = question[:500]
    return {key: value for key, value in output.items() if value not in (None, "")}


def ask_market_agent(
    db: Session, request: AgentChatRequest, memory: dict[str, Any] | None = None
) -> tuple[str, list[AgentSource], list[str], dict[str, Any]]:
    active_memory = dict(memory or {})
    memory_prompt = json.dumps(active_memory, ensure_ascii=False) if active_memory else "暂无"
    messages: list[dict[str, Any]] = [{
        "role": "system",
        "content": SYSTEM_PROMPT + f"\n当前会话结构化记忆：{memory_prompt}。遇到‘它、这个型号、和昨天比’等指代时继承记忆条件；本轮明确给出新条件时覆盖旧条件。",
    }]
    messages.extend({"role": item.role, "content": item.content} for item in request.history[-10:])
    messages.append({"role": "user", "content": request.question})
    sources: list[AgentSource] = []
    tools_used: list[str] = []
    used_arguments: list[dict[str, Any]] = []

    for _ in range(4):
        response = _ollama_chat(
            {
                "model": settings.ollama_model,
                "messages": messages,
                "tools": TOOLS,
                "stream": False,
                "keep_alive": "10m",
                "options": {"temperature": 0.1, "num_predict": 220},
            }
        )
        message = response.get("message") or {}
        calls = message.get("tool_calls") or []
        if not calls:
            answer = _text(message.get("content"))
            if answer:
                unique_sources = list({(item.label, item.detail): item for item in sources}.values())
                return answer, unique_sources[:5], tools_used, _updated_memory(active_memory, request.question, used_arguments)
            break

        messages.append(message)
        for call in calls[:4]:
            function = call.get("function") or {}
            name = _text(function.get("name"))
            arguments = function.get("arguments") or {}
            if not isinstance(arguments, dict):
                arguments = {}
            arguments = _arguments_with_memory(arguments, active_memory)
            used_arguments.append(arguments)
            result = _execute_tool(db, name, arguments)
            sources.extend(result.sources)
            if name and name not in tools_used:
                tools_used.append(name)
            messages.append(
                {
                    "role": "tool",
                    "tool_name": name,
                    "content": json.dumps(result.payload, ensure_ascii=False, default=str),
                }
            )

    raise AgentUnavailableError("智能体未能生成有效回答，请稍后重试")


def _fallback_import_summary(request: ImportAgentSummaryRequest) -> tuple[str, list[str]]:
    source_label = {"excel": "Excel 报价表", "image": "报价图片", "mixed": "混合报价文件"}[request.source_type]
    summary = f"已完成 {source_label}检查，共识别 {request.total_candidates} 条候选报价。"
    recommendations: list[str] = []
    if request.duplicate_candidates:
        recommendations.append(f"优先检查 {request.duplicate_candidates} 条重复报价，避免同日重复入库。")
    if request.abnormal_price_candidates:
        recommendations.append(f"核对 {request.abnormal_price_candidates} 条异常波动及其上期价格。")
    pending_prices = request.no_quote_candidates + request.masked_candidates
    if pending_prices:
        recommendations.append(f"确认 {pending_prices} 条暂无报价或通配价格记录。")
    if request.incomplete_candidates:
        recommendations.append(f"补充 {request.incomplete_candidates} 条型号、容量或颜色不完整记录。")
    if not recommendations:
        recommendations.append("本次没有发现明显风险，可以进入复核工作台。")
    return summary, recommendations[:3]


def summarize_import_agent(request: ImportAgentSummaryRequest) -> tuple[str, list[str], bool]:
    fallback_summary, fallback_recommendations = _fallback_import_summary(request)
    payload = request.model_dump()
    try:
        response = _ollama_chat(
            {
                "model": settings.ollama_model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "你是数据来源导入智能体。根据给定的精确统计生成简洁中文导入总结。"
                            "不得修改、推测或新增数字。summary 不超过 80 字；recommendations 最多 3 条，"
                            "按重复、异常波动、信息不完整、缺价与通配价格的风险顺序给出可执行建议。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"请总结这次报价导入预检：{json.dumps(payload, ensure_ascii=False)}",
                    },
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
        content = _text((response.get("message") or {}).get("content"))
        result = json.loads(content)
        summary = _text(result.get("summary"))
        recommendations = [_text(item) for item in result.get("recommendations", []) if _text(item)]
        if summary:
            return summary, recommendations[:3] or fallback_recommendations, True
    except (AgentUnavailableError, json.JSONDecodeError, TypeError, AttributeError):
        pass
    return fallback_summary, fallback_recommendations, False
