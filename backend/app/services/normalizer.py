import re


SPACE_RE = re.compile(r"\s+")


def normalize_storage(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.upper().replace(" ", "")
    normalized = normalized.replace("GB", "G").replace("TB", "T")
    normalized = re.sub(r"(?<=\d)[/]", "+", normalized)
    return normalized


def normalize_model(value: str) -> str:
    value = value.strip().replace("＋", "+")
    value = re.sub(r"(?i)ultre", "Ultra", value)
    value = re.sub(r"(?i)promax", "Pro Max", value)
    value = re.sub(r"(?i)\bpro\b", "Pro", value)
    value = SPACE_RE.sub(" ", value)
    return value.strip(" _-：:")


def model_key(
    brand: str,
    model_normalized: str,
    storage: str | None,
    color: str | None,
    variant: str | None,
) -> str:
    parts = [brand, model_normalized, storage or "-", color or "-", variant or "-"]
    return "|".join(part.strip().lower() for part in parts)

