from datetime import date
from types import SimpleNamespace

import cv2
import numpy as np

from app.services import ocr_provider


class FakeRapidOcr:
    def __call__(self, image):
        boxes = np.array(
            [
                [[16, 20], [104, 20], [104, 42], [16, 42]],
                [[136, 20], [224, 20], [224, 42], [136, 42]],
                [[256, 20], [344, 20], [344, 42], [256, 42]],
            ],
            dtype=np.float32,
        )
        return SimpleNamespace(
            boxes=boxes,
            txts=(
                "X200s 12+256 黑3460",
                "X300 12+256 黑3660",
                "ViVOY300 8+256 黑1400",
            ),
            scores=(0.99, 0.98, 0.97),
        )


def test_rapidocr_keeps_cells_separate_in_a_three_column_table(tmp_path, monkeypatch) -> None:
    image = np.full((180, 360, 3), 255, dtype=np.uint8)
    for y in (0, 60, 120, 179):
        cv2.line(image, (0, y), (359, y), (0, 0, 0), 2)
    for x in (0, 120, 240, 359):
        cv2.line(image, (x, 0), (x, 179), (0, 0, 0), 2)
    image_path = tmp_path / "three-columns.png"
    assert cv2.imwrite(str(image_path), image)

    monkeypatch.setattr(ocr_provider, "_get_engine", lambda: FakeRapidOcr())
    candidates = ocr_provider.RapidOcrTableProvider().recognize(image_path, date(2026, 8, 20), "VIVO")

    assert [(item.model, item.storage, item.price) for item in candidates] == [
        ("X200s", "12+256", 3460),
        ("X300", "12+256", 3660),
        ("Y300", "8+256", 1400),
    ]
    assert {item.source_line for item in candidates} == {1}
    assert all(item.cell_address.startswith("image:r1:c") for item in candidates)
    assert all(item.source_region_precise is True for item in candidates)
    assert [item.source_x for item in candidates] == [0, 120, 240]
    assert all(item.source_image_width == 360 for item in candidates)

    region = ocr_provider.locate_image_cell(image_path, "image:r1:c2")
    assert region is not None
    assert region.precise is True
    assert region.x < 180 < region.x + region.width
    assert region.y < 30 < region.y + region.height


def test_image_board_is_inferred_from_ocr_text() -> None:
    assert ocr_provider.infer_image_sheet_name("郑州思物通讯 VIVO系列 iQOO15 X200s") == "VIVO"
    assert ocr_provider.infer_image_sheet_name("OPPO Reno15 一加 Ace6 真我GT8") == "OPPO"
    assert ocr_provider.infer_image_sheet_name("红米K80 小米15 红米Note15") == "红米小米"
    assert ocr_provider.infer_image_sheet_name("郑州思物 8.21收货行情 华为融合系列") == "华为融合系列"
    assert ocr_provider.infer_image_sheet_name("没有可识别的品牌词") == "图片自动识别"


def test_top_board_heading_wins_over_product_keywords() -> None:
    tokens = [
        {"text": "郑州思物 8.21收货行情", "x": 400.0, "y": 42.0, "score": 0.99},
        {"text": "华为融合系列", "x": 400.0, "y": 108.0, "score": 0.99},
        {"text": "vivo X200s 12+256 黑3460", "x": 400.0, "y": 480.0, "score": 0.99},
    ]

    assert ocr_provider.infer_image_sheet_name_from_top(tokens, image_height=800) == "华为融合系列"
