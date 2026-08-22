from __future__ import annotations

import base64
import json
import mimetypes
from abc import ABC, abstractmethod
from datetime import date
from pathlib import Path

from app.core.config import settings
from app.services.parser import ParsedCandidate, parse_text_line


class OcrConfigurationError(RuntimeError):
    pass


class OcrProvider(ABC):
    @abstractmethod
    def recognize(self, image_path: Path, quote_date: date, sheet_name: str) -> list[ParsedCandidate]:
        raise NotImplementedError


class ManualTextOcrProvider(OcrProvider):
    def __init__(self, text: str):
        self.text = text

    def recognize(self, image_path: Path, quote_date: date, sheet_name: str) -> list[ParsedCandidate]:
        output: list[ParsedCandidate] = []
        for index, line in enumerate(self.text.splitlines(), start=1):
            output.extend(
                parse_text_line(
                    line,
                    sheet_name=sheet_name,
                    quote_date=quote_date,
                    source_line=index,
                )
            )
        return output


class OpenAIVisionOcrProvider(OcrProvider):
    def recognize(self, image_path: Path, quote_date: date, sheet_name: str) -> list[ParsedCandidate]:
        if not settings.openai_api_key:
            raise OcrConfigurationError("未配置 OPENAI_API_KEY；图片已保存，可填写人工识别文本后重新解析。")

        from openai import OpenAI

        mime = mimetypes.guess_type(image_path.name)[0] or "image/png"
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        client = OpenAI(api_key=settings.openai_api_key)
        response = client.responses.create(
            model=settings.openai_vision_model,
            store=False,
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "识别这张3C数码回收报价表。只提取产品报价行，忽略标题、地址、说明。"
                                "每条 line 保留型号、容量、颜色和价格原文；没有价格或用*遮挡也必须保留。"
                            ),
                        },
                        {
                            "type": "input_image",
                            "image_url": f"data:{mime};base64,{encoded}",
                            "detail": "high",
                        },
                    ],
                }
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "quote_lines",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {"lines": {"type": "array", "items": {"type": "string"}}},
                        "required": ["lines"],
                        "additionalProperties": False,
                    },
                }
            },
        )
        payload = json.loads(response.output_text)
        output: list[ParsedCandidate] = []
        for index, line in enumerate(payload["lines"], start=1):
            output.extend(
                parse_text_line(
                    line,
                    sheet_name=sheet_name,
                    quote_date=quote_date,
                    source_line=index,
                )
            )
        return output

