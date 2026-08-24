from fastapi import HTTPException

from app.api.routes import imports


def test_bulk_upload_creates_one_auto_classified_batch_per_file(monkeypatch) -> None:
    calls = []

    def fake_create_import(*args):
        calls.append(args)
        return f"batch-{len(calls)}"

    monkeypatch.setattr(imports, "create_import", fake_create_import)
    result = imports.upload_imports(
        files=[object(), object()],
        source_name="测试来源",
        quote_date=None,
        manual_text=None,
        db=object(),
    )

    assert result == ["batch-1", "batch-2"]
    assert [call[5] for call in calls] == [None, None]


def test_bulk_upload_rejects_shared_manual_text() -> None:
    try:
        imports.upload_imports(
            files=[object(), object()],
            source_name="测试来源",
            quote_date=None,
            manual_text="不能把同一段文本用于多张图片",
            db=object(),
        )
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "批量图片" in str(exc.detail)
    else:  # pragma: no cover - protects the API contract
        raise AssertionError("批量导入必须拒绝共享人工文本")
