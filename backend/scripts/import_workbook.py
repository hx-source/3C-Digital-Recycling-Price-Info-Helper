from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from sqlalchemy import select
from starlette.datastructures import UploadFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal
from app.models.entities import ImportBatch
from app.services.import_service import create_import


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("用法：python scripts/import_workbook.py <xlsx路径>")
    path = Path(sys.argv[1]).resolve()
    if not path.exists():
        raise SystemExit(f"文件不存在：{path}")
    sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    with SessionLocal() as db:
        existing = db.scalar(
            select(ImportBatch).where(
                ImportBatch.file_sha256 == sha256,
                ImportBatch.filename == path.name,
            ).order_by(ImportBatch.id.desc())
        )
        if existing:
            print(f"已存在批次 #{existing.id}，状态={existing.status.value}，候选={existing.total_candidates}")
            return
        with path.open("rb") as file_handle:
            batch = create_import(
                db,
                UploadFile(filename=path.name, file=file_handle),
                "郑州思物通讯",
                None,
                None,
                None,
            )
        print(f"导入完成：批次 #{batch.id}，状态={batch.status.value}，候选={batch.total_candidates}")


if __name__ == "__main__":
    main()

