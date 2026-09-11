from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy.orm import Session

from app.models.entities import QuoteCandidate, ReviewAuditLog


AUTO_APPROVE = "auto_approve"
REVOKE_AUTO_APPROVE = "revoke_auto_approve"
MANUAL_APPROVE = "manual_approve"
MANUAL_REJECT = "manual_reject"
MANUAL_EDIT = "manual_edit"
AGENT_SUGGESTION_APPLY = "agent_suggestion_apply"
MARK_NO_ISSUE = "mark_no_issue"
SAMPLE_SELECTED = "sample_selected"
SAMPLE_PASSED = "sample_passed"
SAMPLE_FAILED = "sample_failed"

HUMAN = "human"
AGENT = "agent"
SYSTEM = "system"
REVIEW_RULE_VERSION = "review-v2"


SNAPSHOT_FIELDS = (
    "id",
    "batch_id",
    "quote_date",
    "category",
    "brand",
    "model",
    "model_normalized",
    "storage",
    "color",
    "variant",
    "price_status",
    "price",
    "confidence",
    "review_status",
    "review_note",
    "sheet_name",
    "cell_address",
    "source_line",
    "parser_version",
)


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return format(value, ".2f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def candidate_snapshot(candidate: QuoteCandidate) -> dict[str, Any]:
    return {field: _json_value(getattr(candidate, field)) for field in SNAPSHOT_FIELDS}


def changed_fields(before: dict[str, Any] | None, after: dict[str, Any] | None) -> list[str]:
    old = before or {}
    new = after or {}
    return sorted(field for field in set(old) | set(new) if old.get(field) != new.get(field))


def add_audit_log(
    db: Session,
    *,
    action_type: str,
    operator_type: str,
    before_data: dict[str, Any] | None,
    after_data: dict[str, Any] | None,
    batch_id: int | None = None,
    candidate_id: int | None = None,
    reason: str | None = None,
    agent_run_id: str | None = None,
    model_name: str | None = None,
    rule_version: str | None = REVIEW_RULE_VERSION,
) -> ReviewAuditLog:
    log = ReviewAuditLog(
        batch_id=batch_id,
        candidate_id=candidate_id,
        action_type=action_type,
        operator_type=operator_type,
        before_data=before_data,
        after_data=after_data,
        changed_fields=changed_fields(before_data, after_data),
        reason=(reason or "").strip()[:500] or None,
        agent_run_id=agent_run_id,
        model_name=model_name,
        rule_version=rule_version,
    )
    db.add(log)
    return log
