from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from app.models.entities import PriceStatus
from app.services.normalizer import normalize_model, normalize_storage


PARSER_VERSION = "v1.2"

STORAGE_RE = re.compile(
    r"(?P<ram>\d{1,2})\s*[+＋/]\s*(?P<capacity>\d{2,4})\s*(?P<unit>GB|G|TB|T|g|t)?",
    re.IGNORECASE,
)
COMPACT_STORAGE_RE = re.compile(r"(?<!\d)(?P<capacity>128|256|512|1024|1TB|2TB|1T|2T)(?!\d)", re.I)
TRAILING_PRICE_RE = re.compile(r"(?<!\d)(?P<price>\d[\d*]{2,5}|\d{2,5}|\*)(?:\s*)$")
PRICE_TOKEN_RE = r"(?:\d[\d*]{2,5}|\d{2,5}|\*)"

COLOR_WORDS = [
    "原色米兰尼斯", "黑色米兰尼斯", "浅蓝色高山回环", "黑色高山回环", "亮蓝色野径回环",
    "木炭色野径回环", "玫瑰金", "深空灰", "亮黑色", "浮光", "青峰", "墨影", "沙漠",
    "星光", "人鱼", "丹宁", "怀特", "纳维", "格林", "传奇", "赛道", "凌云", "旷野",
    "可可", "白巧", "抹茶", "沙丘", "王牌", "金属", "夏夜", "夏绿", "星海", "青云",
    "浅蓝", "亮蓝", "木炭", "午夜", "银色", "金色", "白色", "黑色", "蓝色", "紫色",
    "绿色", "红色", "灰色", "粉色", "青色", "橙色", "棕色", "黄色", "钛色",
    "黑", "白", "蓝", "紫", "绿", "红", "银", "金", "灰", "粉", "青", "橙", "棕", "黄", "钛", "彩", "浅",
]
COLOR_PATTERN = "|".join(re.escape(item) for item in sorted(COLOR_WORDS, key=len, reverse=True))
COLOR_PRICE_RE = re.compile(
    rf"(?P<color>{COLOR_PATTERN})\s*(?P<price>{PRICE_TOKEN_RE})(?![\d*])(?!\s*(?:款|年|寸|代))",
    re.I,
)
COLOR_SEQUENCE_RE = re.compile(rf"^(?P<colors>(?:{COLOR_PATTERN})+)(?P<masked>\*)?$", re.I)
COLOR_TOKEN_RE = re.compile(COLOR_PATTERN, re.I)

BRAND_PREFIXES: dict[str, tuple[str, ...]] = {
    "Apple": ("Apple", "苹果"),
    "Huawei": ("Huawei", "华为"),
    "Honor": ("Honor", "荣耀"),
    "OPPO": ("OPPO",),
    # OCR occasionally loses the leading "一" in OnePlus models, for example
    # "一加Ace5" becomes "加Ace5".  The short "加" prefix is only stripped
    # after infer_brand has positively identified a OnePlus-style model.
    "OnePlus": ("OnePlus", "一加", "1+", "加"),
    "realme": ("realme", "真我"),
    "vivo": ("vivo",),
    "iQOO": ("iQOO", "iQ00"),
    "Redmi": ("Redmi", "红米"),
    "Xiaomi": ("Xiaomi", "小米"),
    "Lenovo": ("Lenovo", "联想"),
    "ASUS": ("ASUS", "华硕"),
    "DJI": ("DJI", "大疆"),
    "Nintendo": ("Nintendo", "任天堂"),
    "Sony": ("Sony", "索尼"),
    "Canon": ("Canon", "佳能"),
    "Logitech": ("Logitech", "罗技"),
}

ONEPLUS_PREFIX_RE = re.compile(r"^\s*(?:一加|oneplus|1[+＋])", re.IGNORECASE)
ONEPLUS_MISSING_YI_RE = re.compile(
    r"^\s*加\s*(?=(?:ace|turbo|nord|\d))",
    re.IGNORECASE,
)

SKIP_PREFIXES = (
    "注：", "注:", "注意", "地址", "所有机器", "大盘表", "邮寄地址", "白天业务", "退货模板", "寄存模板"
)
SECTION_WORDS = ("系列", "报价参考", "收货行情", "工作表", "价格")

SHEET_META: dict[str, tuple[str, str]] = {
    "苹果手机": ("Apple", "手机"),
    "苹果手表": ("Apple", "智能穿戴"),
    "苹果平板": ("Apple", "平板"),
    "苹果笔记本": ("Apple", "电脑"),
    "华为平板": ("Huawei", "平板"),
    "华为系列": ("Huawei", "手机"),
    "华为融合": ("Huawei", "配件/穿戴"),
    "华为融合系列": ("Huawei", "配件/穿戴"),
    "OPPO": ("OPPO", "手机"),
    "VIVO": ("vivo", "手机"),
    "红米小米": ("Xiaomi", "手机/平板"),
    "小米平板": ("Xiaomi", "平板"),
    "小米融合": ("Xiaomi", "配件/生态"),
    "荣耀报价": ("Honor", "手机/平板"),
    "笔记本电脑": ("Mixed", "电脑"),
    "电玩 大疆 鼠标": ("Mixed", "电玩/影像/外设"),
    "联想OV 平板": ("Mixed", "平板"),
}


@dataclass(slots=True)
class ParsedCandidate:
    raw_text: str
    quote_date: date
    category: str
    brand: str
    model: str
    model_normalized: str
    storage: str | None
    color: str | None
    variant: str | None
    price_status: PriceStatus
    price: Decimal | None
    confidence: float
    sheet_name: str | None = None
    cell_address: str | None = None
    source_line: int | None = None
    source_x: int | None = None
    source_y: int | None = None
    source_width: int | None = None
    source_height: int | None = None
    source_image_width: int | None = None
    source_image_height: int | None = None
    source_region_precise: bool | None = None


def infer_brand(sheet_name: str, text: str) -> str:
    lower = text.lower()
    if ONEPLUS_PREFIX_RE.search(text) or ONEPLUS_MISSING_YI_RE.search(text):
        return "OnePlus"
    if "真我" in text or "realme" in lower:
        return "realme"
    if "iqoo" in lower or "iq00" in lower:
        return "iQOO"
    if "红米" in text or "redmi" in lower or lower.startswith("note"):
        return "Redmi"
    if "小米" in text or lower.startswith("mi "):
        return "Xiaomi"
    if "联想" in text or any(token in lower for token in ("y7000", "y9000", "r7000", "r9000", "thinkbook")):
        return "Lenovo"
    if "华硕" in text or "天选" in text:
        return "ASUS"
    if "大疆" in text or "dji" in lower or "osmo" in lower:
        return "DJI"
    if "任天堂" in text or "switch" in lower:
        return "Nintendo"
    if "索尼" in text or "ps5" in lower:
        return "Sony"
    if "佳能" in text or "eos" in lower:
        return "Canon"
    if "罗技" in text or "logitech" in lower:
        return "Logitech"
    return SHEET_META.get(sheet_name, ("Other", "其他"))[0]


def sheet_category(sheet_name: str) -> str:
    return SHEET_META.get(sheet_name, ("Other", "其他"))[1]


def should_skip(text: str) -> bool:
    value = text.strip()
    if not value or value == "325":
        return True
    if value.startswith(SKIP_PREFIXES):
        return True
    if "系列" in value and not COLOR_PRICE_RE.search(value):
        return True
    if re.fullmatch(r"\d{2}款.*(?:寸|系列)?", value):
        return True
    has_price_signal = bool(re.search(r"\d{3,5}|\*", value))
    has_spec = bool(STORAGE_RE.search(value) or COMPACT_STORAGE_RE.search(value))
    if any(word in value for word in SECTION_WORDS) and not (has_price_signal and has_spec):
        return True
    return False


def _price_status(token: str | None) -> tuple[PriceStatus, Decimal | None]:
    if not token:
        return PriceStatus.NO_QUOTE, None
    if "*" in token:
        return PriceStatus.MASKED, None
    return PriceStatus.QUOTED, Decimal(token)


def _split_shared_colors(color: str) -> list[str]:
    if len(color) > 1 and all(char in "黑白蓝紫绿红银金灰粉青橙棕黄钛彩浅" for char in color):
        return list(dict.fromkeys(color))
    return [color]


def _extract_storage(text: str) -> tuple[str | None, tuple[int, int] | None]:
    match = STORAGE_RE.search(text)
    if match:
        unit = (match.group("unit") or "G").upper()
        storage = f"{match.group('ram')}+{match.group('capacity')}{unit if unit == 'T' else ''}"
        return normalize_storage(storage), match.span()
    compact = COMPACT_STORAGE_RE.search(text)
    if compact and re.search(r"(?i)(iphone|ipad|air|pro|max|note|x\d|s\d|k\d|mate|nova|reno|ace|turbo|neo|iqoo|vivo|oppo|红米|小米)", text):
        return normalize_storage(compact.group("capacity")), compact.span()
    return None, None


def _clean_model_prefix(prefix: str, storage_span: tuple[int, int] | None) -> tuple[str, str | None]:
    working = prefix
    if storage_span:
        working = (prefix[: storage_span[0]] + " " + prefix[storage_span[1] :]).strip()
    variant = None
    for marker in ("柔光版", "灵动版", "悦读版", "至尊版", "卫星版", "活力版", "标准版", "套装"):
        if marker in working:
            variant = marker
            working = working.replace(marker, " ")
    working = re.sub(r"[_—-]+$", "", working).strip()
    return normalize_model(working), variant


def _strip_brand_prefix(model: str, brand: str) -> str:
    result = model
    changed = True
    while changed:
        changed = False
        for prefix in BRAND_PREFIXES.get(brand, ()):
            stripped = re.sub(rf"(?i)^{re.escape(prefix)}[\s·:_-]*", "", result).strip()
            if stripped != result and stripped:
                result = stripped
                changed = True
                break
    return result


def _model_and_variant(prefix: str, storage_span: tuple[int, int] | None, brand: str) -> tuple[str, str | None]:
    model, variant = _clean_model_prefix(prefix, storage_span)
    return _strip_brand_prefix(model, brand), variant


def parse_text_line(
    raw_text: str,
    *,
    sheet_name: str,
    quote_date: date,
    cell_address: str | None = None,
    source_line: int | None = None,
    explicit_price: Decimal | None = None,
) -> list[ParsedCandidate]:
    text = re.sub(r"\s+", " ", str(raw_text).replace("＋", "+")).strip()
    if should_skip(text):
        return []

    brand = infer_brand(sheet_name, text)
    category = sheet_category(sheet_name)
    storage, storage_span = _extract_storage(text)

    if storage_span:
        color_suffix = text[storage_span[1] :].strip()
        sequence = COLOR_SEQUENCE_RE.fullmatch(color_suffix)
        if sequence:
            model, variant = _model_and_variant(text[: storage_span[1]], storage_span, brand)
            status = PriceStatus.MASKED if sequence.group("masked") else PriceStatus.NO_QUOTE
            colors = COLOR_TOKEN_RE.findall(sequence.group("colors"))
            return [
                ParsedCandidate(
                    raw_text=text,
                    quote_date=quote_date,
                    category=category,
                    brand=brand,
                    model=model,
                    model_normalized=normalize_model(model),
                    storage=storage,
                    color=color,
                    variant=variant,
                    price_status=status,
                    price=None,
                    confidence=0.72 if status == PriceStatus.MASKED else 0.68,
                    sheet_name=sheet_name,
                    cell_address=cell_address,
                    source_line=source_line,
                )
                for color in colors
            ]

    color_matches = list(COLOR_PRICE_RE.finditer(text))

    if explicit_price is not None:
        model, variant = _model_and_variant(text, storage_span, brand)
        if not model:
            return []
        return [
            ParsedCandidate(
                raw_text=text,
                quote_date=quote_date,
                category=category,
                brand=brand,
                model=model,
                model_normalized=normalize_model(model),
                storage=storage,
                color=None,
                variant=variant,
                price_status=PriceStatus.QUOTED,
                price=explicit_price,
                confidence=0.96,
                sheet_name=sheet_name,
                cell_address=cell_address,
                source_line=source_line,
            )
        ]

    if color_matches:
        first = color_matches[0]
        prefix = text[: first.start()].strip()
        model, variant = _model_and_variant(
            prefix,
            storage_span if storage_span and storage_span[1] <= first.start() else None,
            brand,
        )
        if not model:
            return []
        results: list[ParsedCandidate] = []
        for match in color_matches:
            status, price = _price_status(match.group("price"))
            for color in _split_shared_colors(match.group("color")):
                results.append(
                    ParsedCandidate(
                        raw_text=text,
                        quote_date=quote_date,
                        category=category,
                        brand=brand,
                        model=model,
                        model_normalized=normalize_model(model),
                        storage=storage,
                        color=color,
                        variant=variant,
                        price_status=status,
                        price=price,
                        confidence=0.92 if status == PriceStatus.QUOTED else 0.72,
                        sheet_name=sheet_name,
                        cell_address=cell_address,
                        source_line=source_line,
                    )
                )
        return results

    trailing = TRAILING_PRICE_RE.search(text)
    if trailing and storage_span and trailing.start() < storage_span[1]:
        trailing = None
    if trailing:
        token = trailing.group("price")
        prefix = text[: trailing.start()].strip(" _:-")
        storage, storage_span = _extract_storage(prefix)
        model, variant = _model_and_variant(prefix, storage_span, brand)
        status, price = _price_status(token)
        if model and (storage or len(model) >= 3):
            return [
                ParsedCandidate(
                    raw_text=text,
                    quote_date=quote_date,
                    category=category,
                    brand=brand,
                    model=model,
                    model_normalized=normalize_model(model),
                    storage=storage,
                    color=None,
                    variant=variant,
                    price_status=status,
                    price=price,
                    confidence=0.86 if status == PriceStatus.QUOTED else 0.65,
                    sheet_name=sheet_name,
                    cell_address=cell_address,
                    source_line=source_line,
                )
            ]

    if storage or "*" in text:
        model, variant = _model_and_variant(text, storage_span, brand)
        colors = [word for word in COLOR_WORDS if word in text[(storage_span or (0, 0))[1] :]]
        return [
            ParsedCandidate(
                raw_text=text,
                quote_date=quote_date,
                category=category,
                brand=brand,
                model=model,
                model_normalized=normalize_model(model),
                storage=storage,
                color="/".join(dict.fromkeys(colors)) or None,
                variant=variant,
                price_status=PriceStatus.MASKED if "*" in text else PriceStatus.NO_QUOTE,
                price=None,
                confidence=0.58,
                sheet_name=sheet_name,
                cell_address=cell_address,
                source_line=source_line,
            )
        ]
    return []


def with_location(candidate: ParsedCandidate, sheet_name: str, cell_address: str) -> ParsedCandidate:
    return replace(candidate, sheet_name=sheet_name, cell_address=cell_address)
