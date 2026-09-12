from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from playwright.sync_api import BrowserContext, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

from app.core.config import BACKEND_DIR, settings
from app.core.database import SessionLocal
from app.services.watched_source_service import import_watched_workbook


DEFAULT_URL = "https://www.kdocs.cn/l/coiFK4Xl4BnU"
AUTH_STATE = BACKEND_DIR / "storage" / "kdocs-auth-state.json"
STATE_FILE = BACKEND_DIR / "storage" / "kdocs-sync-state.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def find_existing_file(directory: Path, digest: str, exclude: Path | None = None) -> Path | None:
    for path in [*directory.glob("*.xlsx"), *directory.glob("*.xlsm")]:
        if exclude is not None and path.resolve(strict=False) == exclude.resolve(strict=False):
            continue
        if path.is_file() and sha256(path) == digest:
            return path
    return None


def safe_stem(value: str) -> str:
    value = re.sub(r"[<>:\"/\\|?*]+", "-", value).strip(" .-")
    return value or "思物通讯每日报价表"


def dismiss_known_dialogs(page: Page) -> None:
    for label in ("我知道了", "关闭"):
        button = page.get_by_role("button", name=label, exact=True)
        if button.count() and button.first.is_visible():
            button.first.click(timeout=3_000)


def wait_for_document(page: Page) -> None:
    page.wait_for_load_state("domcontentloaded", timeout=60_000)
    try:
        page.wait_for_load_state("networkidle", timeout=15_000)
    except PlaywrightTimeoutError:
        pass
    if "account.wps.cn" in page.url:
        raise RuntimeError("金山文档登录已失效，请双击 setup-kdocs-auto-sync.bat 重新登录")
    page.wait_for_function("document.title && document.title !== '金山文档'", timeout=60_000)
    dismiss_known_dialogs(page)


def login_and_save(context: BrowserContext, page: Page, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    print("请在打开的 Edge 中完成金山文档登录，并打开报价表。完成后回到此窗口按回车。", flush=True)
    input()
    if "account.wps.cn" in page.url:
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    wait_for_document(page)
    AUTH_STATE.parent.mkdir(parents=True, exist_ok=True)
    context.storage_state(path=AUTH_STATE)
    print(f"登录状态已保存到本机：{AUTH_STATE}", flush=True)


def download_workbook(url: str, headed: bool, login: bool, watch_dir: Path) -> tuple[Path, str]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=not (headed or login))
        context_options: dict[str, object] = {"accept_downloads": True}
        if AUTH_STATE.exists():
            context_options["storage_state"] = str(AUTH_STATE)
        context = browser.new_context(**context_options)
        page = context.new_page()
        try:
            if login:
                login_and_save(context, page, url)
            else:
                page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                wait_for_document(page)

            # 金山表格顶部第三个按钮为文件操作菜单，下载项会直接生成 XLSX。
            menu_button = page.get_by_role("button").nth(2)
            menu_button.click(timeout=20_000)
            download_option = page.get_by_role("option", name="下载", exact=True)
            download_option.wait_for(state="visible", timeout=20_000)
            with page.expect_download(timeout=90_000) as download_info:
                download_option.click()
            download = download_info.value
            suffix = Path(download.suggested_filename).suffix.lower()
            if suffix not in {".xlsx", ".xlsm"}:
                suffix = ".xlsx"
            temporary = watch_dir / f"kdocs-download-{datetime.now():%Y%m%d%H%M%S%f}.tmp{suffix}"
            download.save_as(str(temporary))
            failure = download.failure()
            if failure:
                raise RuntimeError(f"金山文档下载失败：{failure}")
            if not temporary.exists():
                raise RuntimeError("浏览器未生成下载文件，请重新登录后再试")
            return temporary, safe_stem(Path(download.suggested_filename).stem)
        finally:
            context.close()
            browser.close()


def save_state(payload: dict[str, object]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def sync(url: str, headed: bool, login: bool) -> dict[str, object]:
    watch_dir = settings.upload_dir / "kdocs-daily"
    watch_dir.mkdir(parents=True, exist_ok=True)
    temporary, document_name = download_workbook(url, headed, login, watch_dir)
    try:
        digest = sha256(temporary)
        existing = find_existing_file(watch_dir, digest, exclude=temporary)
        if existing:
            temporary.unlink(missing_ok=True)
            workbook = existing
            download_status = "unchanged"
        else:
            workbook = watch_dir / f"{document_name}_{datetime.now():%Y%m%d_%H%M%S}_{digest[:8]}{temporary.suffix}"
            temporary.replace(workbook)
            download_status = "updated"

        with SessionLocal() as db:
            import_result = import_watched_workbook(db, workbook)
        result: dict[str, object] = {
            "status": download_status,
            "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "document_url": url,
            "file": str(workbook),
            "sha256": digest,
            "import": import_result,
        }
        save_state(result)
        return result
    finally:
        temporary.unlink(missing_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="下载金山文档每日报价表并导入复核工作台")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--headed", action="store_true", help="显示浏览器，便于排查页面变化")
    parser.add_argument("--login", action="store_true", help="显示浏览器并重新保存登录状态")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = sync(args.url, args.headed, args.login)
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        return 0
    except Exception as exc:  # 任务计划需要稳定记录错误并返回非零状态
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
