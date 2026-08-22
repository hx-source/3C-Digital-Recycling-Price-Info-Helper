from __future__ import annotations

import hashlib
import shutil
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.entities import (
    BatchStatus,
    ImportBatch,
    PriceStatus,
    QuoteCandidate,
    ReviewStatus,
    SourceType,
)
from app.services.excel_importer import ExcelQuoteImporter
from app.services.ocr_provider import ManualTextOcrProvider, OcrConfigurationError, OpenAIVisionOcrProvider
from app.services.parser import PARSER_VERSION, ParsedCandidate


ALLOWED_EXCEL = {".xlsx", ".xlsm"}
ALLOWED_IMAGE = {".png", ".jpg", ".jpeg", ".webp"}


def save_upload(upload: UploadFile) -> tuple[Path, str]:
    suffix = Path(upload.filename or "upload").suffix.lower()
    destination_dir = settings.upload_dir / datetime.now().strftime("%Y/%m/%d")
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / f"{uuid4().hex}{suffix}"
    hasher = hashlib.sha256()
    size = 0
    with destination.open("wb") as target:
        while chunk := upload.file.read(1024 * 1024):
            size += len(chunk)
            if size > settings.max_upload_mb * 1024 * 1024:
                target.close()
                destination.unlink(missing_ok=True)
                raise ValueError(f"文件超过 {settings.max_upload_mb} MB 限制")
            hasher.update(chunk)
            target.write(chunk)
    return destination, hasher.hexdigest()


def detect_source_type(filename: str) -> SourceType:
    suffix = Path(filename).suffix.lower()
    if suffix in ALLOWED_EXCEL:
        return SourceType.EXCEL
    if suffix in ALLOWED_IMAGE:
        return SourceType.IMAGE
    raise ValueError("仅支持 xlsx、xlsm、png、jpg、jpeg、webp 文件")


def _persist_candidates(db: Session, batch: ImportBatch, items: list[ParsedCandidate]) -> None:
    records = [
        QuoteCandidate(
            batch_id=batch.id,
            sheet_name=item.sheet_name,
            cell_address=item.cell_address,
            raw_text=item.raw_text,
            source_line=item.source_line,
            quote_date=item.quote_date,
            category=item.category,
            brand=item.brand,
            model=item.model,
            model_normalized=item.model_normalized,
            storage=item.storage,
            color=item.color,
            variant=item.variant,
            price_status=item.price_status,
            price=item.price,
            confidence=item.confidence,
            review_status=ReviewStatus.PENDING,
            parser_version=PARSER_VERSION,
        )
        for item in items
    ]
    db.add_all(records)
    batch.total_candidates = len(records)
    batch.valid_candidates = sum(1 for item in items if item.model and item.brand)
    batch.status = BatchStatus.REVIEW


def create_import(
    db: Session,
    upload: UploadFile,
    source_name: str,
    requested_date: date | None,
    manual_text: str | None,
    image_sheet_name: str | None,
) -> ImportBatch:
    source_type = detect_source_type(upload.filename or "")
    path, sha256 = save_upload(upload)
    batch = ImportBatch(
        source_type=source_type,
        source_name=source_name,
        filename=upload.filename or path.name,
        stored_path=str(path),
        file_sha256=sha256,
        status=BatchStatus.PARSING,
        quote_date=requested_date,
    )
    db.add(batch)
    db.flush()

    fallback_date = requested_date or date.today()
    try:
        if source_type == SourceType.EXCEL:
            items = ExcelQuoteImporter().parse(path, fallback_date)
        else:
            provider = ManualTextOcrProvider(manual_text) if manual_text else OpenAIVisionOcrProvider()
            items = provider.recognize(path, fallback_date, image_sheet_name or "VIVO")
        _persist_candidates(db, batch, items)
    except OcrConfigurationError as exc:
        batch.status = BatchStatus.NEEDS_OCR
        batch.error_message = str(exc)
    except Exception as exc:
        batch.status = BatchStatus.FAILED
        batch.error_message = f"{type(exc).__name__}: {exc}"
    db.commit()
    db.refresh(batch)
    return batch


def reparse_image(
    db: Session, batch: ImportBatch, manual_text: str, image_sheet_name: str, quote_date: date | None
) -> ImportBatch:
    if batch.source_type != SourceType.IMAGE:
        raise ValueError("只有图片批次支持人工文本重解析")
    for candidate in list(batch.candidates):
        db.delete(candidate)
    batch.status = BatchStatus.PARSING
    batch.error_message = None
    items = ManualTextOcrProvider(manual_text).recognize(
        Path(batch.stored_path), quote_date or batch.quote_date or date.today(), image_sheet_name
    )
    _persist_candidates(db, batch, items)
    db.commit()
    db.refresh(batch)
    return batch


def reparse_excel(db: Session, batch: ImportBatch) -> ImportBatch:
    if batch.source_type != SourceType.EXCEL:
        raise ValueError("只有 Excel 批次支持表格重解析")
    if batch.status == BatchStatus.COMMITTED or batch.quotes:
        raise ValueError("已发布批次不能重解析")
    if any(candidate.review_status != ReviewStatus.PENDING for candidate in batch.candidates):
        raise ValueError("批次已有人工作业，不能覆盖重解析")

    batch.status = BatchStatus.PARSING
    batch.error_message = None
    for candidate in list(batch.candidates):
        db.delete(candidate)
    db.flush()

    items = ExcelQuoteImporter().parse(Path(batch.stored_path), batch.quote_date or date.today())
    _persist_candidates(db, batch, items)
    db.commit()
    db.refresh(batch)
    return batch
