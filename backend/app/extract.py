"""항목 추출 — OCR 결과를 Claude에 넣어 의미 단위로 뽑아낸다.

레이아웃 분석까지는 좌표로 풀 수 있지만, "합계금액 → 17,160,000"처럼 의미를 붙이는 건
좌표에 답이 없다. 여기서 LLM을 쓴다.

핵심은 **근거(line_ids)를 같이 받는 것**이다. 값만 받으면 맞는지 확인할 방법이 없다.
줄 번호를 함께 받으면 화면에서 원본 위치를 바로 짚어 줄 수 있고, 존재하지 않는 줄을
가리키면 지어낸 값이라는 신호가 된다.
"""

from __future__ import annotations

import os
import time
from typing import Literal

from pydantic import BaseModel, Field

from .schemas import ExtractedField, ExtractPreset, ExtractResponse, ExtractUsage, LineItem

MODEL = "claude-opus-5"

# claude-opus-5 공개 요금 (2026-08 기준, USD / 100만 토큰)
INPUT_COST_PER_MTOK = 5.00
OUTPUT_COST_PER_MTOK = 25.00

# 추출은 최고 난도 추론이 필요한 작업이 아니다. medium에서 시작해 필요하면 올린다.
EFFORT = "medium"
MAX_TOKENS = 8000

# 정책 거절 시 다른 모델로 자동 재시도. 계정에 이 베타가 없으면 한 번 실패하고 끄고 간다.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

_client = None
_use_fallbacks = True


class MissingAPIKey(RuntimeError):
    pass


def get_client():
    """Anthropic 클라이언트. 키가 없으면 명확한 메시지로 실패한다."""
    global _client
    if _client is not None:
        return _client

    import anthropic

    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        raise MissingAPIKey(
            "ANTHROPIC_API_KEY가 설정되지 않았습니다. "
            "키를 발급받아 backend 실행 전에 export 하세요."
        )

    _client = anthropic.Anthropic()
    return _client


# --- LLM이 채울 스키마 ---------------------------------------------------
# 값은 전부 문자열로 받는다. "1,250,000원", "2026년 8월 16일"처럼 원문 표기를 그대로
# 보존해야 나중에 사람이 대조할 수 있고, 숫자 파싱은 후단에서 하면 된다.


class _Field(BaseModel):
    key: str = Field(description="항목 이름. 문서에 적힌 표현을 그대로 쓴다")
    value: str = Field(description="값. 원문 표기 그대로 옮긴다")
    line_ids: list[int] = Field(description="이 값의 근거가 된 줄 번호. 최소 1개")
    confidence: Literal["high", "medium", "low"] = Field(
        description="문서에 명시돼 있으면 high, 추론이 섞이면 medium, 불확실하면 low"
    )


class _LineItem(BaseModel):
    name: str
    quantity: str = Field(description="없으면 빈 문자열")
    unit_price: str = Field(description="없으면 빈 문자열")
    amount: str = Field(description="없으면 빈 문자열")
    line_ids: list[int]


class _AutoResult(BaseModel):
    doc_type: str = Field(description="문서 종류를 한국어로. 예: 거래명세서, 영수증, 계약서")
    fields: list[_Field]


class _InvoiceResult(BaseModel):
    doc_type: str
    fields: list[_Field] = Field(description="발행일자·공급자·합계금액 등 품목을 뺀 항목들")
    items: list[_LineItem] = Field(description="품목 표의 각 행. 없으면 빈 배열")


_SYSTEM = """너는 한국어 문서 OCR 결과에서 항목을 뽑아내는 추출기다.

입력은 OCR로 읽은 텍스트다. 인식 오류가 섞여 있을 수 있다.

규칙:
- 값은 문서에 적힌 표기를 그대로 옮긴다. 단위·쉼표·괄호를 임의로 정리하지 마라.
  ("1,250,000원"을 1250000으로 바꾸지 마라)
- 모든 항목에 근거가 된 줄 번호를 line_ids로 남긴다. 줄 번호는 반드시 색인에 있는 것만 쓴다.
- 문서에 없는 항목은 만들어내지 마라. 비어 있으면 그 항목을 빼라.
- OCR 오인식으로 보이면(예: 깨진 글자) 값은 보이는 대로 옮기고 confidence를 low로 둔다.
- 표는 이미 마크다운 표로 복원돼 있다. 행/열 관계를 그대로 신뢰해도 된다."""

_PRESET_PROMPT = {
    "auto": "이 문서에서 의미 있는 항목을 모두 뽑아라. 어떤 항목이 있는지는 네가 판단한다.",
    "invoice": (
        "거래명세서·세금계산서·영수증으로 보고 처리하라. "
        "품목 표의 각 행은 items로, 나머지(문서번호·발행일자·공급자·공급받는자·"
        "담당자·공급가액·부가세·합계금액 등)는 fields로 넣어라."
    ),
}

_RESULT_MODEL = {"auto": _AutoResult, "invoice": _InvoiceResult}


def build_prompt(lines: list, markdown: str, preset: ExtractPreset) -> str:
    """마크다운(표 구조) + 줄 번호 색인(근거용)을 함께 준다."""
    index = "\n".join(f"{line.id}: {line.text}" for line in lines)
    document = markdown.strip() or "\n".join(line.text for line in lines)

    return (
        f"{_PRESET_PROMPT[preset]}\n\n"
        "## 문서 (표는 마크다운으로 복원됨)\n"
        f"{document}\n\n"
        "## 줄 번호 색인 (line_ids는 여기 있는 번호만 사용)\n"
        f"{index}"
    )


def _call(client, prompt: str, preset: ExtractPreset):
    """정책 거절 시 fallback으로 재시도. 베타가 없는 계정이면 한 번만 실패하고 끈다."""
    global _use_fallbacks

    kwargs = dict(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        output_config={"effort": EFFORT},
        output_format=_RESULT_MODEL[preset],
        system=_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )

    if _use_fallbacks:
        try:
            return client.beta.messages.parse(
                **kwargs, betas=[FALLBACK_BETA], fallbacks="default"
            )
        except Exception as exc:
            if "fallback" not in str(exc).lower() and "beta" not in str(exc).lower():
                raise
            _use_fallbacks = False  # 이 계정에는 없는 기능. 다음부터 건너뛴다

    return client.messages.parse(**kwargs)


def extract(lines: list, markdown: str, preset: ExtractPreset) -> ExtractResponse:
    """동기 함수 — FastAPI에서는 threadpool로 넘겨서 호출한다."""
    client = get_client()
    prompt = build_prompt(lines, markdown, preset)

    started = time.perf_counter()
    message = _call(client, prompt, preset)
    elapsed_ms = (time.perf_counter() - started) * 1000

    warnings: list[str] = []

    if message.stop_reason == "refusal":
        raise RuntimeError("모델이 이 문서 처리를 거절했습니다.")
    if message.stop_reason == "max_tokens":
        warnings.append("응답이 토큰 한도에서 잘렸습니다. 항목이 누락됐을 수 있습니다.")

    parsed = message.parsed_output
    if parsed is None:
        raise RuntimeError("스키마에 맞는 결과를 받지 못했습니다.")

    valid_ids = {line.id for line in lines}

    def clean(ids: list[int]) -> list[int]:
        """존재하지 않는 줄을 가리키면 지어낸 값일 수 있다. 버리고 경고를 남긴다."""
        kept = [i for i in ids if i in valid_ids]
        if len(kept) != len(ids):
            warnings.append("문서에 없는 줄 번호를 참조한 항목이 있습니다.")
        return kept

    fields = [
        ExtractedField(
            key=f.key,
            value=f.value,
            line_ids=clean(f.line_ids),
            confidence=f.confidence,
        )
        for f in parsed.fields
    ]
    items = [
        LineItem(
            name=i.name,
            quantity=i.quantity,
            unit_price=i.unit_price,
            amount=i.amount,
            line_ids=clean(i.line_ids),
        )
        for i in getattr(parsed, "items", [])
    ]

    usage = message.usage
    cost = (
        usage.input_tokens / 1_000_000 * INPUT_COST_PER_MTOK
        + usage.output_tokens / 1_000_000 * OUTPUT_COST_PER_MTOK
    )

    return ExtractResponse(
        preset=preset,
        doc_type=parsed.doc_type,
        fields=fields,
        items=items,
        warnings=sorted(set(warnings)),
        usage=ExtractUsage(
            model=message.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=round(cost, 5),
            elapsed_ms=round(elapsed_ms, 1),
        ),
    )
