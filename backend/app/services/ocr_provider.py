from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from datetime import date
from functools import lru_cache
from pathlib import Path

from app.services.parser import ParsedCandidate, parse_text_line


class OcrConfigurationError(RuntimeError):
    """Raised when the local OCR runtime is unavailable on this machine."""


@dataclass(frozen=True)
class ImageSourceRegion:
    """A candidate's source cell in original image pixels."""

    x: int
    y: int
    width: int
    height: int
    image_width: int
    image_height: int
    precise: bool


class OcrProvider(ABC):
    @abstractmethod
    def recognize(self, image_path: Path, quote_date: date, sheet_name: str | None = None) -> list[ParsedCandidate]:
        raise NotImplementedError


AUTO_SHEET_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("VIVO", ("vivo", "iqoo", "iQ00", "x200", "x300")),
    ("OPPO", ("oppo", "一加", "oneplus", "realme", "真我", "reno", "find", "ace")),
    ("红米小米", ("红米", "redmi", "小米", "xiaomi", "k80", "k90", "turbo", "note")),
    ("华为系列", ("华为", "huawei", "mate", "nova", "pura")),
    ("荣耀报价", ("荣耀", "honor", "magic")),
    ("电玩 大疆 鼠标", ("大疆", "dji", "switch", "索尼", "sony", "佳能", "canon", "罗技", "logitech", "ps5")),
)

HEADER_SHEET_RULES: tuple[tuple[str, str], ...] = (
    ("华为融合系列", "华为融合系列"),
    ("华为融合", "华为融合"),
    ("华为系列", "华为系列"),
    ("VIVO系列", "VIVO"),
    ("OPPO系列", "OPPO"),
    ("红米/小米", "红米小米"),
    ("红米小米", "红米小米"),
    ("荣耀报价", "荣耀报价"),
    ("荣耀系列", "荣耀报价"),
    ("电玩", "电玩 大疆 鼠标"),
)


def infer_image_sheet_name(text: str) -> str:
    """Prefer the image's board heading, then fall back to product keywords."""
    normalized = "".join(text.lower().split())
    for header_text, board_name in HEADER_SHEET_RULES:
        if header_text.lower() in normalized:
            return board_name
    scores = [
        (sum(normalized.count(keyword.lower()) for keyword in keywords), sheet_name)
        for sheet_name, keywords in AUTO_SHEET_RULES
    ]
    score, sheet_name = max(scores, default=(0, "图片自动识别"))
    return sheet_name if score else "图片自动识别"


def infer_image_sheet_name_from_top(tokens: list[dict[str, float | str]], image_height: int) -> str:
    """The board normally sits directly below the title/date in the upper band of a quote image."""
    top_band = " ".join(
        str(token["text"])
        for token in tokens
        if float(token["y"]) <= image_height * 0.30
    )
    board_name = infer_image_sheet_name(top_band)
    if board_name != "图片自动识别":
        return board_name
    return infer_image_sheet_name(" ".join(str(token["text"]) for token in tokens))


class ManualTextOcrProvider(OcrProvider):
    """Fallback for correcting a problematic image without changing its source file."""

    def __init__(self, text: str):
        self.text = text

    def recognize(self, image_path: Path, quote_date: date, sheet_name: str | None = None) -> list[ParsedCandidate]:
        resolved_sheet_name = sheet_name or infer_image_sheet_name(self.text)
        output: list[ParsedCandidate] = []
        for index, line in enumerate(self.text.splitlines(), start=1):
            output.extend(
                parse_text_line(
                    line,
                    sheet_name=resolved_sheet_name,
                    quote_date=quote_date,
                    source_line=index,
                )
            )
        return output


@lru_cache(maxsize=1)
def _get_engine():
    try:
        from rapidocr import RapidOCR
    except ImportError as exc:  # pragma: no cover - only happens on incomplete installations
        raise OcrConfigurationError(
            "本地 OCR 组件未安装。请在 backend 目录执行 pip install -r requirements.txt，"
            "或粘贴人工识别文本。"
        ) from exc
    return RapidOCR()


def _merge_positions(positions: list[int], tolerance: int = 5) -> list[int]:
    if not positions:
        return []
    groups: list[list[int]] = [[value] for value in sorted(positions)]
    merged: list[list[int]] = [groups[0]]
    for group in groups[1:]:
        if group[0] - merged[-1][-1] <= tolerance:
            merged[-1].extend(group)
        else:
            merged.append(group)
    return [round(sum(group) / len(group)) for group in merged]


def _table_lines(image, axis: str) -> list[int]:
    """Find long table rules. The returned positions are image coordinates."""
    import cv2

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 35, 9
    )
    height, width = gray.shape
    if axis == "horizontal":
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(60, width // 25), 1))
        minimum_span = width * 0.48
        coordinate = lambda x, y, w, h: y + h // 2
    else:
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(60, height // 25)))
        minimum_span = height * 0.38
        coordinate = lambda x, y, w, h: x + w // 2

    rules = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
    contours, _ = cv2.findContours(rules, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    positions = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        span = w if axis == "horizontal" else h
        if span >= minimum_span:
            positions.append(coordinate(x, y, w, h))
    return _merge_positions(positions, tolerance=max(4, min(width, height) // 700))


def _index_between(value: float, boundaries: list[int]) -> int | None:
    for index, (start, end) in enumerate(zip(boundaries, boundaries[1:])):
        if start <= value <= end:
            return index
    return None


def _cluster_rows(tokens: list[dict[str, float | str]], image_height: int) -> list[list[dict[str, float | str]]]:
    """Fallback for images without visible table rules."""
    rows: list[list[dict[str, float | str]]] = []
    threshold = max(18, image_height * 0.012)
    for token in sorted(tokens, key=lambda item: (float(item["y"]), float(item["x"]))):
        if not rows or float(token["y"]) - float(rows[-1][-1]["y"]) > threshold:
            rows.append([token])
        else:
            rows[-1].append(token)
    return rows


def _image_tokens(image) -> list[dict[str, float | str]]:
    result = _get_engine()(image)
    if not result.txts or result.boxes is None:
        return []

    tokens: list[dict[str, float | str]] = []
    for box, text, score in zip(result.boxes, result.txts, result.scores or ()):  # OCR boxes are quadrilaterals
        cleaned = str(text).strip()
        if not cleaned:
            continue
        xs = [float(point[0]) for point in box]
        ys = [float(point[1]) for point in box]
        tokens.append(
            {
                "text": cleaned,
                "score": float(score),
                "x": sum(xs) / len(xs),
                "y": sum(ys) / len(ys),
                "x0": min(xs),
                "x1": max(xs),
                "y0": min(ys),
                "y1": max(ys),
            }
        )
    return tokens


def _read_image(image_path: Path):
    try:
        import cv2
        import numpy as np
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise OcrConfigurationError("本地图片处理组件未安装，请重新安装 backend 依赖。") from exc

    image_bytes = np.fromfile(str(image_path), dtype=np.uint8)
    image = cv2.imdecode(image_bytes, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("无法读取图片文件")
    return image


def _cell_target(cell_address: str | None) -> tuple[int, int] | None:
    if not cell_address:
        return None
    import re

    match = re.fullmatch(r"image:r(\d+):c(\d+)", cell_address)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _region_for_cell(
    cell_tokens: list[dict[str, float | str]],
    *,
    row_index: int,
    column: int,
    horizontal: list[int],
    vertical: list[int],
    image_width: int,
    image_height: int,
    has_row_rules: bool,
    has_column_rules: bool,
) -> ImageSourceRegion:
    """Return a grid cell when possible, otherwise the OCR text bounds."""
    if has_row_rules and has_column_rules:
        return ImageSourceRegion(
            x=max(0, vertical[column]),
            y=max(0, horizontal[row_index]),
            width=max(1, vertical[column + 1] - vertical[column]),
            height=max(1, horizontal[row_index + 1] - horizontal[row_index]),
            image_width=image_width,
            image_height=image_height,
            precise=True,
        )
    x0 = max(0, int(min(float(token["x0"]) for token in cell_tokens)) - 8)
    x1 = min(image_width, int(max(float(token["x1"]) for token in cell_tokens)) + 8)
    y0 = max(0, int(min(float(token["y0"]) for token in cell_tokens)) - 8)
    y1 = min(image_height, int(max(float(token["y1"]) for token in cell_tokens)) + 8)
    return ImageSourceRegion(
        x=x0,
        y=y0,
        width=max(1, x1 - x0),
        height=max(1, y1 - y0),
        image_width=image_width,
        image_height=image_height,
        precise=False,
    )


def locate_image_cell(image_path: Path, cell_address: str | None) -> ImageSourceRegion | None:
    """Rebuild a table grid and return the original-image rectangle for an image candidate."""
    target = _cell_target(cell_address)
    if target is None:
        return None

    image = _read_image(image_path)
    height, width = image.shape[:2]
    tokens = _image_tokens(image)
    if not tokens:
        return None

    horizontal = _table_lines(image, "horizontal")
    vertical = _table_lines(image, "vertical")
    has_row_rules = len(horizontal) >= 3
    has_column_rules = len(vertical) >= 2
    if has_row_rules:
        horizontal = _merge_positions([0, *horizontal, height])
        row_groups: list[list[dict[str, float | str]]] = [[] for _ in range(len(horizontal) - 1)]
        for token in tokens:
            row = _index_between(float(token["y"]), horizontal)
            if row is not None:
                row_groups[row].append(token)
    else:
        row_groups = _cluster_rows(tokens, height)
    if has_column_rules:
        vertical = _merge_positions([0, *vertical, width])

    target_row, target_column = target
    source_line = 0
    for row_index, row in enumerate(row_groups):
        if not row:
            continue
        source_line += 1
        if source_line != target_row:
            continue
        cells: dict[int, list[dict[str, float | str]]] = {}
        for token in row:
            column = _index_between(float(token["x"]), vertical) if has_column_rules else 0
            if column is not None:
                cells.setdefault(column, []).append(token)
        cell_tokens = cells.get(target_column - 1)
        if not cell_tokens:
            return None
        return _region_for_cell(
            cell_tokens,
            row_index=row_index,
            column=target_column - 1,
            horizontal=horizontal,
            vertical=vertical,
            image_width=width,
            image_height=height,
            has_row_rules=has_row_rules,
            has_column_rules=has_column_rules,
        )
    return None


class RapidOcrTableProvider(OcrProvider):
    """Offline OCR that uses table rules and OCR coordinates to preserve column order."""

    def recognize(self, image_path: Path, quote_date: date, sheet_name: str | None = None) -> list[ParsedCandidate]:
        try:
            import cv2
            import numpy as np
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise OcrConfigurationError("本地图片处理组件未安装，请重新安装 backend 依赖。") from exc

        image = _read_image(image_path)
        tokens = _image_tokens(image)

        if not tokens:
            return []

        height, width = image.shape[:2]
        resolved_sheet_name = sheet_name or infer_image_sheet_name_from_top(tokens, height)
        horizontal = _table_lines(image, "horizontal")
        vertical = _table_lines(image, "vertical")
        has_row_rules = len(horizontal) >= 3
        has_column_rules = len(vertical) >= 2
        if has_row_rules:
            horizontal = _merge_positions([0, *horizontal, height])
            row_groups: list[list[dict[str, float | str]]] = [[] for _ in range(len(horizontal) - 1)]
            for token in tokens:
                row = _index_between(float(token["y"]), horizontal)
                if row is not None:
                    row_groups[row].append(token)
        else:
            row_groups = _cluster_rows(tokens, height)

        if has_column_rules:
            vertical = _merge_positions([0, *vertical, width])

        output: list[ParsedCandidate] = []
        source_line = 0
        for row_index, row in enumerate(row_groups):
            if not row:
                continue
            source_line += 1
            cells: dict[int, list[dict[str, float | str]]] = {}
            for token in row:
                column = _index_between(float(token["x"]), vertical) if has_column_rules else 0
                if column is not None:
                    cells.setdefault(column, []).append(token)

            for column, cell_tokens in sorted(cells.items()):
                ordered = sorted(cell_tokens, key=lambda item: float(item["x"]))
                text = " ".join(str(item["text"]) for item in ordered)
                ocr_score = sum(float(item["score"]) for item in ordered) / len(ordered)
                region = _region_for_cell(
                    cell_tokens,
                    row_index=row_index,
                    column=column,
                    horizontal=horizontal,
                    vertical=vertical,
                    image_width=width,
                    image_height=height,
                    has_row_rules=has_row_rules,
                    has_column_rules=has_column_rules,
                )
                candidates = parse_text_line(
                    text,
                    sheet_name=resolved_sheet_name,
                    quote_date=quote_date,
                    cell_address=f"image:r{source_line}:c{column + 1}",
                    source_line=source_line,
                )
                output.extend(
                    replace(
                        candidate,
                        confidence=round(min(candidate.confidence, ocr_score), 3),
                        source_x=region.x,
                        source_y=region.y,
                        source_width=region.width,
                        source_height=region.height,
                        source_image_width=region.image_width,
                        source_image_height=region.image_height,
                        source_region_precise=region.precise,
                    )
                    for candidate in candidates
                )
        return output
