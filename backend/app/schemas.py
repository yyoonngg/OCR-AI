"""API 응답 스키마 (Pydantic v2)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# RapidOCR가 제공하는 인식 모델 언어. 필요하면 여기에 더 추가하면 된다.
LangCode = Literal["korean", "ch", "en", "japan", "latin"]


class BBox(BaseModel):
    """축 정렬 사각형. 프론트에서 오버레이를 그릴 때 쓴다."""

    x: float
    y: float
    width: float
    height: float


class TextLine(BaseModel):
    id: int
    text: str = Field(description="띄어쓰기 복원까지 끝난 최종 텍스트")
    raw_text: str = Field(description="인식 모델이 그대로 내놓은 원본 텍스트")
    spacing_fixed: bool = Field(description="띄어쓰기 복원으로 text가 바뀌었는지")
    confidence: float = Field(description="0~1 사이 인식 신뢰도")
    polygon: list[tuple[float, float]] = Field(
        description="기울어진 텍스트까지 감싸는 4점 다각형 (좌상단부터 시계방향)"
    )
    bbox: BBox
    page: int = 1
    block_id: int | None = Field(
        default=None, description="레이아웃 분석으로 배정된 블록 id"
    )
    reading_index: int | None = Field(
        default=None, description="읽는 순서 (0부터). 검출 순서와 다를 수 있다"
    )


class Cell(BaseModel):
    row: int
    column: int
    text: str
    line_ids: list[int]
    bbox: BBox


class LayoutBlock(BaseModel):
    id: int
    kind: Literal["text", "table"]
    page: int
    page_column: int = Field(description="2단 편집일 때 몇 번째 단인지 (0부터)")
    bbox: BBox
    text: str = Field(description="text 블록의 내용. 표는 빈 문자열")
    line_ids: list[int]
    rows: int = 0
    columns: int = 0
    has_header: bool = Field(
        default=False, description="첫 행이 머리글인지. 항목-값 표는 머리글이 없다"
    )
    cells: list[Cell] = []


QualityLevel = Literal["good", "fair", "poor"]


class QualityReport(BaseModel):
    level: QualityLevel
    avg_confidence: float
    median_line_height: float = Field(description="줄 높이 중앙값(px). 작을수록 위험하다")
    low_confidence_lines: int
    notes: list[str]


class Timing(BaseModel):
    detect_ms: float
    classify_ms: float
    recognize_ms: float
    spacing_ms: float
    # 괘선 검출. layout_ms에 포함된 값을 따로 떼어 보여 준다.
    rules_ms: float = 0.0
    layout_ms: float
    total_ms: float


PageSource = Literal["ocr", "pdf_text"]


class PageInfo(BaseModel):
    page: int
    width: int
    height: int
    image_data_url: str = Field(description="화면에 그대로 띄울 수 있는 base64 PNG")
    source: PageSource = Field(
        default="ocr", description="pdf_text면 OCR 없이 PDF 텍스트 레이어에서 읽은 것"
    )


class OCRResponse(BaseModel):
    filename: str
    lang: LangCode
    pages: list[PageInfo]
    lines: list[TextLine]
    blocks: list[LayoutBlock]
    full_text: str = Field(description="읽는 순서대로 정렬된 텍스트")
    raw_text: str = Field(description="띄어쓰기 복원 전, 검출 순서 그대로의 텍스트. 비교용")
    markdown: str = Field(description="표를 파이프 표로 살린 마크다운")
    spacing_fixed_lines: int
    quality: QualityReport
    table_count: int
    page_columns: int = Field(description="검출된 최대 단(段) 수. 1이면 단일 단")
    timing: Timing
    engine: str


class HealthResponse(BaseModel):
    status: Literal["ok"]
    engine: str
    warm_langs: list[str]
    extract_ready: bool = Field(description="LLM 항목 추출을 쓸 수 있는지 (API 키 유무)")


# --- 항목 추출 (LLM) -----------------------------------------------------

ExtractPreset = Literal["auto", "invoice"]


class ExtractLine(BaseModel):
    id: int
    text: str
    page: int = 1


class ExtractRequest(BaseModel):
    lines: list[ExtractLine]
    markdown: str = ""
    preset: ExtractPreset = "auto"


class ExtractedField(BaseModel):
    key: str
    value: str
    line_ids: list[int] = Field(description="근거가 된 OCR 줄. 화면에서 원본 위치를 짚어준다")
    confidence: Literal["high", "medium", "low"]


class LineItem(BaseModel):
    name: str
    quantity: str
    unit_price: str
    amount: str
    line_ids: list[int]


class ExtractUsage(BaseModel):
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    elapsed_ms: float


class ExtractResponse(BaseModel):
    preset: ExtractPreset
    doc_type: str
    fields: list[ExtractedField]
    items: list[LineItem]
    warnings: list[str]
    usage: ExtractUsage
