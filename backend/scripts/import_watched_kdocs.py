from __future__ import annotations

import json
from pathlib import Path

from app.core.config import settings
from app.core.database import SessionLocal
from app.services.watched_source_service import import_new_watched_workbooks


def main() -> None:
    watch_dir = settings.upload_dir / "kdocs-daily"
    with SessionLocal() as db:
        results = import_new_watched_workbooks(db, watch_dir)
    print(json.dumps({"watch_dir": str(watch_dir), "results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
