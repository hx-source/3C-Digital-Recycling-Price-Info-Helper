from __future__ import annotations

import json
import os
import sys
import warnings
from tempfile import gettempdir
from pathlib import Path

from dotenv import dotenv_values
from PIL import Image
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


TEST_DB = "price_radar_test_e2e"
BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
configured_url_value = dotenv_values(BACKEND_DIR / ".env").get("DATABASE_URL")
if not configured_url_value:
    raise RuntimeError("请先从 .env.example 创建 backend/.env 并配置 DATABASE_URL")
configured_url = make_url(configured_url_value)
ADMIN_URL = configured_url.set(database="mysql").render_as_string(hide_password=False)
TEST_URL = configured_url.set(database=TEST_DB).render_as_string(hide_password=False)
os.environ["DATABASE_URL"] = TEST_URL
sys.path.insert(0, str(BACKEND_DIR))

root_engine = create_engine(ADMIN_URL)
with root_engine.begin() as connection:
    connection.execute(text(f"CREATE DATABASE IF NOT EXISTS `{TEST_DB}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"))

warnings.filterwarnings(
    "ignore",
    message=r"Using `httpx` with `starlette\.testclient` is deprecated.*",
)
from fastapi.testclient import TestClient

from app.core.database import Base, engine
from app.main import app


Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)

workbook_value = sys.argv[1] if len(sys.argv) > 1 else os.getenv("E2E_WORKBOOK_PATH")
if not workbook_value:
    raise SystemExit("用法：python scripts/e2e_smoke.py <测试报价表.xlsx>")
workbook_path = Path(workbook_value).resolve()
image_path = Path(gettempdir()) / "price-radar-e2e-sample.png"
Image.new("RGB", (16, 16), color=(23, 60, 54)).save(image_path)
assert workbook_path.exists(), workbook_path
assert image_path.exists(), image_path

with TestClient(app) as client:
    health = client.get("/health")
    assert health.status_code == 200

    with workbook_path.open("rb") as file_handle:
        response = client.post(
            "/api/v1/imports",
            files={"file": (workbook_path.name, file_handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            data={"source_name": "郑州思物通讯"},
        )
    assert response.status_code == 201, response.text
    excel_batch = response.json()
    assert excel_batch["status"] == "review"
    assert excel_batch["total_candidates"] > 1000

    response = client.post(
        f"/api/v1/imports/{excel_batch['id']}/review-all",
        params={"review_status": "approved"},
    )
    assert response.status_code == 200, response.text
    response = client.post(f"/api/v1/imports/{excel_batch['id']}/commit")
    assert response.status_code == 200, response.text
    excel_commit = response.json()

    manual_text = "\n".join(
        [
            "X200s 12+256 黑3500白3500蓝3490紫3490",
            "X300pro 12+256 黑白蓝",
            "IQOO15 12+256 传奇42*0赛道42*0",
        ]
    )
    with image_path.open("rb") as file_handle:
        response = client.post(
            "/api/v1/imports",
            files={"file": (image_path.name, file_handle, "image/png")},
            data={
                "source_name": "郑州思物通讯",
                "quote_date": "2026-08-21",
                "image_sheet_name": "VIVO",
                "manual_text": manual_text,
            },
        )
    assert response.status_code == 201, response.text
    image_batch = response.json()
    assert image_batch["status"] == "review"
    assert image_batch["total_candidates"] == 9

    response = client.get(f"/api/v1/imports/{image_batch['id']}/candidates", params={"page_size": 100})
    assert response.status_code == 200
    image_candidates = response.json()["items"]
    assert any(item["price_status"] == "no_quote" for item in image_candidates)
    assert any(item["price_status"] == "masked" for item in image_candidates)

    response = client.post(
        f"/api/v1/imports/{image_batch['id']}/review-all",
        params={"review_status": "approved"},
    )
    assert response.status_code == 200
    response = client.post(f"/api/v1/imports/{image_batch['id']}/commit")
    assert response.status_code == 200, response.text
    image_commit = response.json()

    response = client.get("/api/v1/quotes/changes", params={"search": "X200s"})
    assert response.status_code == 200, response.text
    changes = response.json()
    black = next(item for item in changes if item["color"] == "黑" and item["storage"] == "12+256")
    assert black["current_price"] == "3500.00"
    assert black["previous_price"] == "3460.00"
    assert black["change_amount"] == "40.00"

    response = client.get(f"/api/v1/quotes/{black['model_key']}/history")
    assert response.status_code == 200, response.text
    history = response.json()
    assert history == [
        {"quote_date": "2026-08-20", "price": "3460.00"},
        {"quote_date": "2026-08-21", "price": "3500.00"},
    ]

    response = client.get("/api/v1/dashboard/summary")
    assert response.status_code == 200
    dashboard = response.json()
    assert dashboard["latest_quote_date"] == "2026-08-21"
    assert dashboard["today_increases"] >= 1

print(
    json.dumps(
        {
            "health": health.json(),
            "excel_batch": {"candidates": excel_batch["total_candidates"], "published": excel_commit["inserted"]},
            "image_batch": {"candidates": image_batch["total_candidates"], "published": image_commit["inserted"]},
            "verified_change": black,
            "verified_history": history,
            "dashboard": {
                "latest_quote_date": dashboard["latest_quote_date"],
                "published_quotes": dashboard["published_quotes"],
                "today_increases": dashboard["today_increases"],
            },
        },
        ensure_ascii=False,
        indent=2,
        default=str,
    )
)
image_path.unlink(missing_ok=True)
