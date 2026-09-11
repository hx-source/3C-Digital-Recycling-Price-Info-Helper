from app.models.entities import ImportTask, ImportTaskItem, ImportTaskItemStatus, ImportTaskStatus
from app.services.import_task_service import _recalculate


def make_item(position: int, status: ImportTaskItemStatus, progress: int) -> ImportTaskItem:
    return ImportTaskItem(
        position=position,
        filename=f"file-{position}.xlsx",
        stored_path=f"uploads/file-{position}.xlsx",
        file_sha256="a" * 64,
        status=status,
        stage=status.value,
        progress=progress,
    )


def test_recalculate_uses_persisted_per_file_progress() -> None:
    task = ImportTask(
        id="task-id",
        status=ImportTaskStatus.RUNNING,
        source_name="测试来源",
        total_files=3,
        items=[
            make_item(0, ImportTaskItemStatus.COMPLETED, 100),
            make_item(1, ImportTaskItemStatus.PROCESSING, 40),
            make_item(2, ImportTaskItemStatus.QUEUED, 0),
        ],
    )

    _recalculate(task)

    assert task.progress == 47
    assert task.completed_files == 1
    assert task.succeeded_files == 1
    assert task.failed_files == 0


def test_recalculate_counts_failures_as_finished_files() -> None:
    task = ImportTask(
        id="task-id",
        status=ImportTaskStatus.RUNNING,
        source_name="测试来源",
        total_files=2,
        items=[
            make_item(0, ImportTaskItemStatus.COMPLETED, 100),
            make_item(1, ImportTaskItemStatus.FAILED, 100),
        ],
    )

    _recalculate(task)

    assert task.progress == 100
    assert task.completed_files == 2
    assert task.succeeded_files == 1
    assert task.failed_files == 1
