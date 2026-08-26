from datetime import date
from pathlib import Path
import re
import tempfile
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import case, delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.entities import BatchStatus, ImportBatch, PriceQuote, PriceStatus, QuoteCandidate, ReviewStatus, SourceType
from app.schemas.quotes import (
    BatchSummary,
    BatchQuoteDateUpdate,
    BulkReviewRequest,
    CandidateFilterSummary,
    CandidatePage,
    CandidateRead,
    CandidateSourcePreview,
    CandidateUpdate,
    CommitResult,
    ExcelPrecheckResult,
    PurgeAllDataRequest,
    SourceGroupReplaceRequest,
    SourceLineReparseRequest,
)
from app.services.import_service import candidate_from_parsed, create_import, detect_source_type, reparse_excel, reparse_image
from app.services.excel_importer import ExcelQuoteImporter
from app.services.excel_precheck import inspect_excel_candidates
from app.services.excel_source_preview import build_excel_source_context
from app.services.ocr_provider import OcrConfigurationError, locate_image_cell
from app.services.parser import parse_text_line
from app.services.quote_service import commit_batch, update_candidate


router = APIRouter()


def _stored_source_region(candidate: QuoteCandidate) -> dict[str, int | bool] | None:
    values = (
        candidate.source_x,
        candidate.source_y,
        candidate.source_width,
        candidate.source_height,
        candidate.source_image_width,
        candidate.source_image_height,
        candidate.source_region_precise,
    )
    if any(value is None for value in values):
        return None
    return {
        "x": candidate.source_x,
        "y": candidate.source_y,
        "width": candidate.source_width,
        "height": candidate.source_height,
        "image_width": candidate.source_image_width,
        "image_height": candidate.source_image_height,
        "precise": candidate.source_region_precise,
    }


def _cache_source_region(candidate: QuoteCandidate, located) -> dict[str, int | bool]:
    candidate.source_x = located.x
    candidate.source_y = located.y
    candidate.source_width = located.width
    candidate.source_height = located.height
    candidate.source_image_width = located.image_width
    candidate.source_image_height = located.image_height
    candidate.source_region_precise = located.precise
    return _stored_source_region(candidate)  # type: ignore[return-value]


def _incomplete_candidate_condition():
    """Only flag fields that make a candidate unsafe to publish; missing colour/storage can be valid."""
    return or_(
        QuoteCandidate.model == "",
        QuoteCandidate.model_normalized == "",
        QuoteCandidate.brand == "Other",
        QuoteCandidate.sheet_name == "图片自动识别",
    )


def _looks_like_merged_source_line(raw_text: str) -> bool:
    """A quote cell normally has one storage spec; two often means adjacent OCR rows were merged."""
    return len(re.findall(r"\d{1,2}\s*\+\s*(?:\d{3,4}|1\s*[Tt])", raw_text)) >= 2


def _source_group_filters(candidate: QuoteCandidate):
    filters = [QuoteCandidate.batch_id == candidate.batch_id]
    if candidate.cell_address:
        # Excel sheets reuse addresses such as B4.  A cell is only a unique
        # source location when its worksheet is included as well.
        filters.extend(
            [
                QuoteCandidate.cell_address == candidate.cell_address,
                QuoteCandidate.sheet_name == candidate.sheet_name,
            ]
        )
    elif candidate.source_line is not None:
        filters.extend(
            [
                QuoteCandidate.sheet_name == candidate.sheet_name,
                QuoteCandidate.source_line == candidate.source_line,
            ]
        )
    else:
        filters.append(QuoteCandidate.id == candidate.id)
    return filters


def _refresh_batch_candidate_counts(db: Session, batch: ImportBatch) -> None:
    """Keep the batch summary in sync after replacing or deleting candidates."""
    batch.total_candidates = db.scalar(
        select(func.count(QuoteCandidate.id)).where(QuoteCandidate.batch_id == batch.id)
    ) or 0
    batch.valid_candidates = db.scalar(
        select(func.count(QuoteCandidate.id)).where(
            QuoteCandidate.batch_id == batch.id,
            QuoteCandidate.model.is_not(None),
            QuoteCandidate.model != "",
            QuoteCandidate.brand.is_not(None),
            QuoteCandidate.brand != "",
        )
    ) or 0


def _ensure_candidates_deletable(candidates: list[QuoteCandidate]) -> None:
    if any(candidate.batch.status == BatchStatus.COMMITTED for candidate in candidates):
        raise HTTPException(status_code=409, detail="已发布的报价不能删除")
    if any(candidate.quote is not None for candidate in candidates):
        raise HTTPException(status_code=409, detail="已生成历史报价的记录不能删除")


def _remove_managed_source_file(batch: ImportBatch) -> None:
    """Only unlink files inside the application's upload directory."""
    source_path = Path(batch.stored_path).resolve(strict=False)
    upload_root = settings.upload_dir.resolve(strict=False)
    if not source_path.is_relative_to(upload_root) or not source_path.is_file():
        return
    try:
        source_path.unlink()
    except OSError as exc:
        raise HTTPException(status_code=500, detail="原始文件无法删除，请关闭正在预览该图片的窗口后重试") from exc


@router.post("", response_model=BatchSummary, status_code=status.HTTP_201_CREATED)
def upload_import(
    file: UploadFile = File(...),
    source_name: str = Form("郑州思物通讯"),
    quote_date: date | None = Form(None),
    manual_text: str | None = Form(None),
    image_sheet_name: str | None = Form(None),
    excel_import_mode: Literal["all", "normal_only"] = Form("all"),
    db: Session = Depends(get_db),
) -> ImportBatch:
    try:
        return create_import(db, file, source_name, quote_date, manual_text, image_sheet_name, excel_import_mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/bulk", response_model=list[BatchSummary], status_code=status.HTTP_201_CREATED)
def upload_imports(
    files: list[UploadFile] = File(...),
    source_name: str = Form("郑州思物通讯"),
    quote_date: date | None = Form(None),
    manual_text: str | None = Form(None),
    excel_import_mode: Literal["all", "normal_only"] = Form("all"),
    db: Session = Depends(get_db),
) -> list[ImportBatch]:
    if not files:
        raise HTTPException(status_code=400, detail="请至少选择一个报价文件")
    if len(files) > 30:
        raise HTTPException(status_code=400, detail="单次最多导入 30 个文件")
    if manual_text and len(files) > 1:
        raise HTTPException(status_code=400, detail="批量图片请留空人工文本；每张图片会自动识别板块")
    try:
        return [
            create_import(db, upload, source_name, quote_date, manual_text, None, excel_import_mode)
            for upload in files
        ]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/precheck-excel", response_model=ExcelPrecheckResult)
def precheck_excel_import(
    file: UploadFile = File(...),
    quote_date: date | None = Form(None),
    db: Session = Depends(get_db),
) -> dict:
    """Read one workbook without creating a batch so the user can choose an import strategy."""
    try:
        source_type = detect_source_type(file.filename or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="预检仅支持 XLSX 或 XLSM 表格") from exc
    if source_type != SourceType.EXCEL:
        raise HTTPException(status_code=400, detail="预检仅支持 XLSX 或 XLSM 表格")

    suffix = Path(file.filename or "workbook.xlsx").suffix.lower()
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp_file:
            temp_path = Path(temp_file.name)
            total_size = 0
            while chunk := file.file.read(1024 * 1024):
                total_size += len(chunk)
                if total_size > settings.max_upload_mb * 1024 * 1024:
                    raise HTTPException(status_code=400, detail=f"文件超过 {settings.max_upload_mb} MB 限制")
                temp_file.write(chunk)
        parsed = ExcelQuoteImporter().parse(temp_path, quote_date or date.today())
        existing_quotes = list(db.scalars(select(PriceQuote)).all())
        return inspect_excel_candidates(parsed, existing_quotes).as_dict()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"表格预检失败：{type(exc).__name__}: {exc}") from exc
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


@router.get("/candidates/{candidate_id}/source", response_model=CandidateSourcePreview)
def get_candidate_source(candidate_id: int, db: Session = Depends(get_db)) -> CandidateSourcePreview:
    candidate = db.get(QuoteCandidate, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="候选记录不存在")
    batch = candidate.batch
    if batch.source_type.value != "image":
        excel_path = Path(batch.stored_path)
        if not excel_path.is_file():
            raise HTTPException(status_code=404, detail="原始表格不存在或已被移动")
        try:
            context = build_excel_source_context(excel_path, candidate.sheet_name, candidate.cell_address)
            message = "蓝框为识别的型号描述；黄框为独立价格单元格。"
        except ValueError as exc:
            context = None
            message = str(exc)
        except Exception:
            context = None
            message = "表格片段暂时无法读取，仍可根据工作表、单元格地址和原文核对。"
        return CandidateSourcePreview(
            source_type=batch.source_type,
            filename=batch.filename,
            sheet_name=candidate.sheet_name,
            cell_address=candidate.cell_address,
            raw_text=candidate.raw_text,
            excel_context=context,
            message=message,
        )

    image_path = Path(batch.stored_path)
    if not image_path.is_file():
        raise HTTPException(status_code=404, detail="原始图片不存在或已被移动")
    region = _stored_source_region(candidate)
    message = None
    if region is None:
        try:
            located = locate_image_cell(image_path, candidate.cell_address)
            if located:
                related_candidates = db.scalars(
                    select(QuoteCandidate).where(
                        QuoteCandidate.batch_id == candidate.batch_id,
                        QuoteCandidate.cell_address == candidate.cell_address,
                    )
                ).all()
                for related_candidate in related_candidates:
                    _cache_source_region(related_candidate, located)
                region = _stored_source_region(candidate)
                db.commit()
            else:
                message = "未能定位到该单元格，仍可查看原图与识别原文。"
        except OcrConfigurationError as exc:
            message = str(exc)
        except Exception:
            db.rollback()
            message = "定位时遇到异常，仍可查看原图与识别原文。"
    return CandidateSourcePreview(
        source_type=batch.source_type,
        filename=batch.filename,
        sheet_name=candidate.sheet_name,
        cell_address=candidate.cell_address,
        raw_text=candidate.raw_text,
        image_url=f"/api/v1/imports/{batch.id}/source-image",
        region=region,
        message=message,
    )


@router.get("/candidates/{candidate_id}/source-group", response_model=list[CandidateRead])
def get_candidate_source_group(candidate_id: int, db: Session = Depends(get_db)) -> list[QuoteCandidate]:
    """Return every parsed quote that came from the same image cell / Excel line."""
    candidate = db.get(QuoteCandidate, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="候选记录不存在")

    return list(
        db.scalars(select(QuoteCandidate).where(*_source_group_filters(candidate)).order_by(QuoteCandidate.id)).all()
    )


@router.post("/candidates/{candidate_id}/reparse-source-line", response_model=list[CandidateRead])
def reparse_candidate_source_line(
    candidate_id: int,
    payload: SourceLineReparseRequest,
    db: Session = Depends(get_db),
) -> list[QuoteCandidate]:
    """Replace all candidates from one source location after a human corrects its raw text."""
    candidate = db.get(QuoteCandidate, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="候选记录不存在")
    batch = candidate.batch
    if batch.status == BatchStatus.COMMITTED:
        raise HTTPException(status_code=409, detail="已发布批次不能重新拆分来源行")

    corrected_text = payload.raw_text.strip()
    parsed = parse_text_line(
        corrected_text,
        sheet_name=candidate.sheet_name or "图片自动识别",
        quote_date=candidate.quote_date,
        cell_address=candidate.cell_address,
        source_line=candidate.source_line,
    )
    if not parsed:
        raise HTTPException(status_code=400, detail="修正后的原文未解析出报价，请检查型号、容量和颜色价格格式")

    existing = list(
        db.scalars(select(QuoteCandidate).where(*_source_group_filters(candidate)).order_by(QuoteCandidate.id)).all()
    )
    for item in existing:
        if item.quote is not None:
            raise HTTPException(status_code=409, detail="这行已有报价历史，不能重新拆分")

    records = [candidate_from_parsed(batch.id, item) for item in parsed]
    for record in records:
        record.confidence = 0.99
        record.source_x = candidate.source_x
        record.source_y = candidate.source_y
        record.source_width = candidate.source_width
        record.source_height = candidate.source_height
        record.source_image_width = candidate.source_image_width
        record.source_image_height = candidate.source_image_height
        record.source_region_precise = candidate.source_region_precise
    for item in existing:
        db.delete(item)
    db.flush()
    db.add_all(records)
    db.flush()
    _refresh_batch_candidate_counts(db, batch)
    db.commit()
    return records


@router.put("/candidates/{candidate_id}/source-group", response_model=list[CandidateRead])
def replace_candidate_source_group(
    candidate_id: int,
    payload: SourceGroupReplaceRequest,
    db: Session = Depends(get_db),
) -> list[QuoteCandidate]:
    """Apply edits, additions and removals for a single image cell / Excel source row as one change."""
    anchor = db.get(QuoteCandidate, candidate_id)
    if not anchor:
        raise HTTPException(status_code=404, detail="候选记录不存在")
    existing = list(db.scalars(select(QuoteCandidate).where(*_source_group_filters(anchor))).all())
    _ensure_candidates_deletable(existing)

    existing_by_id = {candidate.id: candidate for candidate in existing}
    kept_ids: set[int] = set()
    output: list[QuoteCandidate] = []
    for item in payload.items:
        values = item.model_dump(exclude={"id"}, exclude_unset=True)
        if item.id is not None:
            candidate = existing_by_id.get(item.id)
            if not candidate:
                raise HTTPException(status_code=400, detail="保存的记录不属于当前来源行")
            try:
                update_candidate(candidate, values)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            if not candidate.brand.strip() or not candidate.model.strip():
                raise HTTPException(status_code=400, detail="报价必须填写品牌和型号")
            candidate.confidence = 1.0
            kept_ids.add(candidate.id)
            output.append(candidate)
            continue

        candidate = QuoteCandidate(
            batch_id=anchor.batch_id,
            sheet_name=anchor.sheet_name,
            cell_address=anchor.cell_address,
            raw_text=anchor.raw_text,
            source_line=anchor.source_line,
            source_x=anchor.source_x,
            source_y=anchor.source_y,
            source_width=anchor.source_width,
            source_height=anchor.source_height,
            source_image_width=anchor.source_image_width,
            source_image_height=anchor.source_image_height,
            source_region_precise=anchor.source_region_precise,
            quote_date=anchor.quote_date,
            category=anchor.category,
            brand="",
            model="",
            model_normalized="",
            storage=None,
            color=None,
            variant=None,
            price_status=PriceStatus.QUOTED,
            price=None,
            confidence=1.0,
            review_status=ReviewStatus.PENDING,
        )
        try:
            update_candidate(candidate, values)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not candidate.brand.strip() or not candidate.model.strip():
            raise HTTPException(status_code=400, detail="新增报价必须填写品牌和型号")
        db.add(candidate)
        output.append(candidate)

    for candidate in existing:
        if candidate.id not in kept_ids:
            db.delete(candidate)
    db.flush()
    _refresh_batch_candidate_counts(db, anchor.batch)
    db.commit()
    return output


@router.delete("/candidates/{candidate_id}")
def delete_candidate(candidate_id: int, db: Session = Depends(get_db)) -> dict[str, int]:
    """Delete one un-published review candidate without affecting sibling colors/prices."""
    candidate = db.get(QuoteCandidate, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="候选记录不存在")
    _ensure_candidates_deletable([candidate])

    batch = candidate.batch
    db.delete(candidate)
    db.flush()
    _refresh_batch_candidate_counts(db, batch)
    db.commit()
    return {"deleted": 1}


@router.delete("/candidates/{candidate_id}/source-group")
def delete_candidate_source_group(candidate_id: int, db: Session = Depends(get_db)) -> dict[str, int]:
    """Delete every review candidate parsed from the same source image cell / Excel row."""
    candidate = db.get(QuoteCandidate, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="候选记录不存在")

    candidates = list(db.scalars(select(QuoteCandidate).where(*_source_group_filters(candidate))).all())
    _ensure_candidates_deletable(candidates)
    batch = candidate.batch
    for item in candidates:
        db.delete(item)
    db.flush()
    _refresh_batch_candidate_counts(db, batch)
    db.commit()
    return {"deleted": len(candidates)}


@router.get("/{batch_id}/source-image")
def get_source_image(batch_id: int, db: Session = Depends(get_db)) -> FileResponse:
    batch = db.get(ImportBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="导入批次不存在")
    if batch.source_type.value != "image":
        raise HTTPException(status_code=400, detail="该批次不是图片来源")
    image_path = Path(batch.stored_path)
    if not image_path.is_file():
        raise HTTPException(status_code=404, detail="原始图片不存在或已被移动")
    return FileResponse(image_path, filename=batch.filename)


@router.get("", response_model=list[BatchSummary])
def list_imports(db: Session = Depends(get_db), limit: int = Query(30, ge=1, le=200)) -> list[ImportBatch]:
    return list(db.scalars(select(ImportBatch).order_by(ImportBatch.created_at.desc()).limit(limit)).all())


@router.get("/{batch_id}", response_model=BatchSummary)
def get_import(batch_id: int, db: Session = Depends(get_db)) -> ImportBatch:
    batch = db.get(ImportBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="导入批次不存在")
    return batch


@router.delete("/purge-all")
def purge_all_import_data(
    payload: PurgeAllDataRequest,
    db: Session = Depends(get_db),
) -> dict[str, int]:
    """Permanently remove every import, candidate, published quote, and managed source file."""
    if payload.confirmation.strip() != "清空全部数据":
        raise HTTPException(status_code=400, detail="请输入“清空全部数据”以确认此操作")

    batches = list(db.scalars(select(ImportBatch)).all())
    deleted_batches = len(batches)
    deleted_candidates = db.scalar(select(func.count(QuoteCandidate.id))) or 0
    deleted_quotes = db.scalar(select(func.count(PriceQuote.id))) or 0

    # Keep the same managed-upload guard as single-batch deletion: data outside
    # the application's upload directory is never touched.
    for batch in batches:
        _remove_managed_source_file(batch)

    try:
        # PriceQuote references both candidates and batches, so delete it first
        # instead of relying on database-specific cascading behaviour.
        db.execute(delete(PriceQuote))
        db.execute(delete(QuoteCandidate))
        db.execute(delete(ImportBatch))
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "deleted_batches": deleted_batches,
        "deleted_candidates": deleted_candidates,
        "deleted_quotes": deleted_quotes,
    }


@router.delete("/{batch_id}")
def delete_import(batch_id: int, db: Session = Depends(get_db)) -> dict[str, int]:
    """Remove one un-published upload together with its review candidates and source file."""
    batch = db.get(ImportBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="导入批次不存在")
    if batch.status == BatchStatus.COMMITTED:
        raise HTTPException(status_code=409, detail="已发布批次不能删除")
    has_quotes = db.scalar(
        select(func.count(PriceQuote.id)).where(PriceQuote.batch_id == batch.id)
    ) or 0
    if has_quotes:
        raise HTTPException(status_code=409, detail="该批次已生成报价历史，不能删除")

    deleted_candidates = db.scalar(
        select(func.count(QuoteCandidate.id)).where(QuoteCandidate.batch_id == batch.id)
    ) or 0
    _remove_managed_source_file(batch)
    db.delete(batch)
    db.commit()
    return {"deleted_batches": 1, "deleted_candidates": deleted_candidates}


@router.patch("/{batch_id}/quote-date", response_model=BatchSummary)
def update_import_quote_date(
    batch_id: int,
    payload: BatchQuoteDateUpdate,
    db: Session = Depends(get_db),
) -> ImportBatch:
    """Correct an import date and keep review records and published quote history aligned."""
    batch = db.get(ImportBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="导入批次不存在")

    batch.quote_date = payload.quote_date
    db.execute(
        update(QuoteCandidate)
        .where(QuoteCandidate.batch_id == batch.id)
        .values(quote_date=payload.quote_date)
    )
    db.execute(
        update(PriceQuote)
        .where(PriceQuote.batch_id == batch.id)
        .values(quote_date=payload.quote_date)
    )
    db.commit()
    db.refresh(batch)
    return batch


@router.post("/{batch_id}/reopen-review")
def reopen_import_for_review(batch_id: int, db: Session = Depends(get_db)) -> dict[str, int]:
    """Withdraw one published batch without deleting its source or review candidates."""
    batch = db.get(ImportBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="导入批次不存在")
    if batch.status != BatchStatus.COMMITTED:
        raise HTTPException(status_code=409, detail="只有已发布批次可以撤回到复核")

    removed_quotes = db.execute(delete(PriceQuote).where(PriceQuote.batch_id == batch.id)).rowcount or 0
    reset_candidates = db.execute(
        update(QuoteCandidate)
        .where(QuoteCandidate.batch_id == batch.id)
        .values(review_status=ReviewStatus.PENDING)
    ).rowcount or 0
    batch.status = BatchStatus.REVIEW
    batch.committed_at = None
    db.commit()
    return {"batch_id": batch.id, "removed_quotes": removed_quotes, "reset_candidates": reset_candidates}


@router.get("/{batch_id}/candidates", response_model=CandidatePage)
def list_candidates(
    batch_id: int,
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=300),
    review_status: ReviewStatus | None = None,
    sheet_name: str | None = None,
    price_status: PriceStatus | None = None,
    filter_mode: Literal["all", "low_confidence", "incomplete", "merged_source"] = "all",
    search: str | None = Query(None, max_length=120),
    sort: Literal["confidence_asc", "confidence_desc", "source_asc"] = "confidence_asc",
) -> CandidatePage:
    base_filters = [QuoteCandidate.batch_id == batch_id]
    summary_row = db.execute(
        select(
            func.count().label("all"),
            func.coalesce(func.sum(case((QuoteCandidate.review_status == ReviewStatus.PENDING, 1), else_=0)), 0).label("pending"),
            func.coalesce(func.sum(case((QuoteCandidate.confidence < 0.75, 1), else_=0)), 0).label("low_confidence"),
            func.coalesce(func.sum(case((_incomplete_candidate_condition(), 1), else_=0)), 0).label("incomplete"),
            func.coalesce(func.sum(case((QuoteCandidate.review_status == ReviewStatus.APPROVED, 1), else_=0)), 0).label("approved"),
            func.coalesce(func.sum(case((QuoteCandidate.review_status == ReviewStatus.REJECTED, 1), else_=0)), 0).label("rejected"),
        ).where(*base_filters)
    ).one()
    all_batch_candidates = list(db.scalars(select(QuoteCandidate).where(*base_filters)).all())
    merged_candidates = [candidate for candidate in all_batch_candidates if _looks_like_merged_source_line(candidate.raw_text)]
    merged_source_keys = {
        candidate.cell_address or f"{candidate.sheet_name}:{candidate.source_line}" or str(candidate.id)
        for candidate in merged_candidates
    }
    summary = CandidateFilterSummary(
        **{key: int(value) for key, value in summary_row._mapping.items()},
        merged_source_groups=len(merged_source_keys),
    )

    filters = list(base_filters)
    if review_status:
        filters.append(QuoteCandidate.review_status == review_status)
    if sheet_name:
        filters.append(QuoteCandidate.sheet_name == sheet_name)
    if price_status:
        filters.append(QuoteCandidate.price_status == price_status)
    if filter_mode == "low_confidence":
        filters.append(QuoteCandidate.confidence < 0.75)
    if filter_mode == "incomplete":
        filters.append(_incomplete_candidate_condition())
    if filter_mode == "merged_source":
        filters.append(QuoteCandidate.id.in_([candidate.id for candidate in merged_candidates] or [-1]))
    if search:
        keyword = f"%{search.strip()}%"
        filters.append(
            or_(
                QuoteCandidate.model.ilike(keyword),
                QuoteCandidate.storage.ilike(keyword),
                QuoteCandidate.color.ilike(keyword),
                QuoteCandidate.raw_text.ilike(keyword),
            )
        )

    ordering = {
        "confidence_asc": (QuoteCandidate.confidence.asc(), QuoteCandidate.source_line, QuoteCandidate.id),
        "confidence_desc": (QuoteCandidate.confidence.desc(), QuoteCandidate.source_line, QuoteCandidate.id),
        "source_asc": (QuoteCandidate.sheet_name, QuoteCandidate.source_line, QuoteCandidate.id),
    }[sort]
    total = db.scalar(select(func.count()).select_from(QuoteCandidate).where(*filters)) or 0
    items = db.scalars(
        select(QuoteCandidate)
        .where(*filters)
        .order_by(*ordering)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return CandidatePage(items=list(items), total=total, page=page, page_size=page_size, summary=summary)


@router.patch("/candidates/{candidate_id}", response_model=CandidateRead)
def patch_candidate(candidate_id: int, payload: CandidateUpdate, db: Session = Depends(get_db)) -> QuoteCandidate:
    candidate = db.get(QuoteCandidate, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="候选记录不存在")
    try:
        update_candidate(candidate, payload.model_dump(exclude_unset=True))
        db.commit()
        db.refresh(candidate)
        return candidate
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{batch_id}/bulk-review")
def bulk_review(batch_id: int, payload: BulkReviewRequest, db: Session = Depends(get_db)) -> dict[str, int]:
    candidates = db.scalars(
        select(QuoteCandidate).where(
            QuoteCandidate.batch_id == batch_id,
            QuoteCandidate.id.in_(payload.candidate_ids),
        )
    ).all()
    for candidate in candidates:
        candidate.review_status = payload.review_status
    db.commit()
    return {"updated": len(candidates)}


@router.post("/{batch_id}/review-all")
def review_all(
    batch_id: int,
    review_status: ReviewStatus = Query(...),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    candidates = db.scalars(select(QuoteCandidate).where(QuoteCandidate.batch_id == batch_id)).all()
    for candidate in candidates:
        candidate.review_status = review_status
    db.commit()
    return {"updated": len(candidates)}


@router.post("/{batch_id}/reparse-image", response_model=BatchSummary)
def reparse_image_endpoint(
    batch_id: int,
    manual_text: str = Form(...),
    quote_date: date | None = Form(None),
    db: Session = Depends(get_db),
) -> ImportBatch:
    batch = db.get(ImportBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="导入批次不存在")
    try:
        return reparse_image(db, batch, manual_text, None, quote_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{batch_id}/reparse-excel", response_model=BatchSummary)
def reparse_excel_endpoint(batch_id: int, db: Session = Depends(get_db)) -> ImportBatch:
    batch = db.get(ImportBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="导入批次不存在")
    try:
        return reparse_excel(db, batch)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{batch_id}/commit", response_model=CommitResult)
def commit_import(batch_id: int, db: Session = Depends(get_db)) -> CommitResult:
    batch = db.get(ImportBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="导入批次不存在")
    try:
        inserted, skipped = commit_batch(db, batch)
        return CommitResult(batch_id=batch.id, inserted=inserted, skipped=skipped, status=batch.status)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
