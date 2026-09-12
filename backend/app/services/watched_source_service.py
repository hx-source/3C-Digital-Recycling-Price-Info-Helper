from __future__ import annotations

import hashlib
from collections import Counter
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.entities import ImportBatch
from app.services.excel_importer import ExcelQuoteImporter
from app.services.excel_precheck import inspect_excel_candidates
from app.services.import_service import create_import_from_saved
from app.models.entities import PriceQuote


class WatchedSourceError(ValueError):
    pass


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest()


def import_watched_workbook(db: Session, path: Path, source_name: str = "金山文档每日自动下载") -> dict:
    resolved = path.resolve(strict=True)
    upload_root = settings.upload_dir.resolve(strict=False)
    if not resolved.is_relative_to(upload_root):
        raise WatchedSourceError("自动监测文件必须位于系统上传目录内")
    if resolved.suffix.lower() not in {".xlsx", ".xlsm"}:
        raise WatchedSourceError("自动监测目前只支持 XLSX 或 XLSM")
    digest = _sha256(resolved)
    existing = db.scalar(select(ImportBatch).where(ImportBatch.file_sha256 == digest).order_by(ImportBatch.id.desc()).limit(1))
    if existing:
        return {"status": "duplicate", "batch_id": existing.id, "sha256": digest, "filename": resolved.name}

    parsed = ExcelQuoteImporter().parse(resolved, date.today())
    precheck = inspect_excel_candidates(parsed, list(db.scalars(select(PriceQuote)).all()))
    precheck_data = precheck.as_dict()
    inferred_date = Counter(item.quote_date for item in parsed).most_common(1)[0][0] if parsed else None
    batch = create_import_from_saved(
        db=db, path=resolved, filename=resolved.name, sha256=digest, source_name=source_name,
        requested_date=inferred_date, manual_text=None, image_sheet_name=None, excel_import_mode="all",
    )
    return {
        "status": "imported" if batch.status.value == "review" else "failed",
        "batch_id": batch.id,
        "batch_status": batch.status.value,
        "sha256": digest,
        "filename": resolved.name,
        "total_candidates": precheck_data["total_candidates"],
        "normal_candidates": precheck_data["normal_candidates"],
        "needs_review_candidates": precheck_data["needs_review_candidates"],
        "duplicate_candidates": precheck.duplicate_candidates,
        "abnormal_price_candidates": precheck.abnormal_price_candidates,
        "error_message": batch.error_message,
    }


def import_new_watched_workbooks(db: Session, directory: Path) -> list[dict]:
    resolved = directory.resolve(strict=False)
    resolved.mkdir(parents=True, exist_ok=True)
    files = sorted(
        [*resolved.glob("*.xlsx"), *resolved.glob("*.xlsm")],
        key=lambda item: item.stat().st_mtime,
    )
    return [import_watched_workbook(db, path) for path in files]
