from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.entities import ImportBatch, QuoteCandidate, ReviewStatus
from app.schemas.quotes import (
    BatchSummary,
    BulkReviewRequest,
    CandidatePage,
    CandidateRead,
    CandidateUpdate,
    CommitResult,
)
from app.services.import_service import create_import, reparse_excel, reparse_image
from app.services.quote_service import commit_batch, update_candidate


router = APIRouter()


@router.post("", response_model=BatchSummary, status_code=status.HTTP_201_CREATED)
def upload_import(
    file: UploadFile = File(...),
    source_name: str = Form("郑州思物通讯"),
    quote_date: date | None = Form(None),
    manual_text: str | None = Form(None),
    image_sheet_name: str | None = Form(None),
    db: Session = Depends(get_db),
) -> ImportBatch:
    try:
        return create_import(db, file, source_name, quote_date, manual_text, image_sheet_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=list[BatchSummary])
def list_imports(db: Session = Depends(get_db), limit: int = Query(30, ge=1, le=200)) -> list[ImportBatch]:
    return list(db.scalars(select(ImportBatch).order_by(ImportBatch.created_at.desc()).limit(limit)).all())


@router.get("/{batch_id}", response_model=BatchSummary)
def get_import(batch_id: int, db: Session = Depends(get_db)) -> ImportBatch:
    batch = db.get(ImportBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="导入批次不存在")
    return batch


@router.get("/{batch_id}/candidates", response_model=CandidatePage)
def list_candidates(
    batch_id: int,
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=300),
    review_status: ReviewStatus | None = None,
    sheet_name: str | None = None,
) -> CandidatePage:
    filters = [QuoteCandidate.batch_id == batch_id]
    if review_status:
        filters.append(QuoteCandidate.review_status == review_status)
    if sheet_name:
        filters.append(QuoteCandidate.sheet_name == sheet_name)
    total = db.scalar(select(func.count()).select_from(QuoteCandidate).where(*filters)) or 0
    items = db.scalars(
        select(QuoteCandidate)
        .where(*filters)
        .order_by(QuoteCandidate.sheet_name, QuoteCandidate.source_line, QuoteCandidate.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return CandidatePage(items=list(items), total=total, page=page, page_size=page_size)


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
    image_sheet_name: str = Form("VIVO"),
    quote_date: date | None = Form(None),
    db: Session = Depends(get_db),
) -> ImportBatch:
    batch = db.get(ImportBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="导入批次不存在")
    try:
        return reparse_image(db, batch, manual_text, image_sheet_name, quote_date)
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
