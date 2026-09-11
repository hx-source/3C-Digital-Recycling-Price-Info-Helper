from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import (
    BatchStatus,
    ImportTask,
    ImportTaskItem,
    ImportTaskItemStatus,
    ImportTaskStatus,
)
from app.services.import_service import create_import_from_saved


def _recalculate(task: ImportTask) -> None:
    finished = [item for item in task.items if item.status in {ImportTaskItemStatus.COMPLETED, ImportTaskItemStatus.FAILED}]
    task.completed_files = len(finished)
    task.succeeded_files = sum(item.status == ImportTaskItemStatus.COMPLETED for item in task.items)
    task.failed_files = sum(item.status == ImportTaskItemStatus.FAILED for item in task.items)
    if task.total_files:
        task.progress = round(sum(item.progress for item in task.items) / task.total_files)


def run_import_task(task_id: str) -> None:
    """Process queued files outside the request session and persist every visible transition."""
    with SessionLocal() as db:
        task = db.scalar(select(ImportTask).where(ImportTask.id == task_id))
        if not task:
            return
        task.status = ImportTaskStatus.RUNNING
        task.started_at = task.started_at or datetime.now()
        task.completed_at = None
        task.error_message = None
        db.commit()

        queued_ids = [item.id for item in task.items if item.status == ImportTaskItemStatus.QUEUED]
        for item_id in queued_ids:
            item = db.get(ImportTaskItem, item_id)
            task = db.get(ImportTask, task_id)
            if not item or not task:
                continue
            task.current_filename = item.filename
            item.status = ImportTaskItemStatus.PROCESSING
            item.stage = "parsing"
            item.progress = 10
            item.started_at = datetime.now()
            item.completed_at = None
            item.error_message = None
            db.commit()

            def report(stage: str, progress: int) -> None:
                current = db.get(ImportTaskItem, item_id)
                parent = db.get(ImportTask, task_id)
                if not current or not parent:
                    return
                current.stage = stage
                current.progress = progress
                _recalculate(parent)
                db.commit()

            try:
                batch = create_import_from_saved(
                    db=db,
                    path=Path(item.stored_path),
                    filename=item.filename,
                    sha256=item.file_sha256,
                    source_name=task.source_name,
                    requested_date=task.quote_date,
                    manual_text=task.manual_text if task.total_files == 1 else None,
                    image_sheet_name=None,
                    excel_import_mode=task.excel_import_mode,
                    progress_callback=report,
                )
                item = db.get(ImportTaskItem, item_id)
                if not item:
                    continue
                item.batch_id = batch.id
                item.candidate_count = batch.total_candidates
                item.progress = 100
                item.completed_at = datetime.now()
                if batch.status in {BatchStatus.REVIEW, BatchStatus.COMMITTED}:
                    item.status = ImportTaskItemStatus.COMPLETED
                    item.stage = "completed"
                else:
                    item.status = ImportTaskItemStatus.FAILED
                    item.stage = "failed"
                    item.error_message = batch.error_message or "识别未生成可复核结果"
            except Exception as exc:
                db.rollback()
                item = db.get(ImportTaskItem, item_id)
                if item:
                    item.status = ImportTaskItemStatus.FAILED
                    item.stage = "failed"
                    item.progress = 100
                    item.error_message = f"{type(exc).__name__}: {exc}"
                    item.completed_at = datetime.now()

            task = db.get(ImportTask, task_id)
            if task:
                _recalculate(task)
            db.commit()

        task = db.get(ImportTask, task_id)
        if not task:
            return
        _recalculate(task)
        task.current_filename = None
        task.completed_at = datetime.now()
        if task.failed_files == 0:
            task.status = ImportTaskStatus.COMPLETED
        elif task.succeeded_files:
            task.status = ImportTaskStatus.PARTIAL_FAILED
        else:
            task.status = ImportTaskStatus.FAILED
            task.error_message = "所有文件均处理失败"
        task.progress = 100
        db.commit()
