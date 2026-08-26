from openpyxl import Workbook

from app.services.excel_source_preview import build_excel_source_context


def test_excel_source_preview_marks_description_and_price_cells(tmp_path) -> None:
    path = tmp_path / "source.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "OPPO"
    sheet["B4"] = "一加Ace5 12+256 黑白"
    sheet["C4"] = 2850
    sheet.merge_cells("B2:C2")
    sheet["B2"] = "OPPO 一加 Ace 系列"
    workbook.save(path)

    context = build_excel_source_context(path, "OPPO", "B4:C4")

    assert context["sheet_name"] == "OPPO"
    assert context["source_cell"] == "B4"
    assert context["price_cell"] == "C4"
    cells = [cell for row in context["rows"] for cell in row["cells"]]
    assert next(cell for cell in cells if cell["coordinate"] == "B4")["is_source"] is True
    assert next(cell for cell in cells if cell["coordinate"] == "C4")["is_price"] is True
