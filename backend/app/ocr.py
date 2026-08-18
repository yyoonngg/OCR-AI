"""RapidOCR(ONNX Runtime) 래퍼.

- 언어별 엔진 인스턴스를 캐싱한다 (모델 로딩이 수 초 걸리므로 매 요청마다 만들면 안 됨).
- 입력은 이미지 또는 PDF. PDF는 pypdfium2로 페이지를 래스터화한 뒤 페이지별로 OCR한다.
"""

from __future__ import annotations

import base64
import io
import threading
import time
from dataclasses import dataclass

import numpy as np
from PIL import Image

from . import layout, pdftext, quality, rules, spacing
from .schemas import BBox, LangCode, LayoutBlock, OCRResponse, PageInfo, Timing, TextLine

ENGINE_NAME = "RapidOCR 3.x / PP-OCRv6-det + PP-OCRv5-rec (ONNX Runtime, CPU)"

# 스캔본은 300dpi 기준으로 폭이 2500px를 넘는 경우가 흔한데,
# 그대로 넣으면 느리기만 하고 정확도 이득이 없다.
MAX_SIDE = 2000
PDF_RENDER_SCALE = 2.0  # 72dpi * 2 = 144dpi. 스캔 PDF에 무난한 값.
MAX_PDF_PAGES = 5

_engines: dict[str, object] = {}
_lock = threading.Lock()


def get_engine(lang: LangCode):
    """언어별 RapidOCR 인스턴스를 만들어 캐싱한다."""
    if lang in _engines:
        return _engines[lang]

    with _lock:
        if lang in _engines:  # 락 대기 중에 다른 스레드가 만들었을 수 있다
            return _engines[lang]

        from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR

        lang_rec = {
            "korean": LangRec.KOREAN,
            "ch": LangRec.CH,
            "en": LangRec.EN,
            "japan": LangRec.JAPAN,
            "latin": LangRec.LATIN,
        }[lang]

        params = {"Rec.lang_type": lang_rec}
        if lang in ("korean", "japan", "latin"):
            # 이 언어들은 PP-OCRv6 인식 모델이 아직 없어서 v5 mobile을 쓴다.
            params["Rec.model_type"] = ModelType.MOBILE
            params["Rec.ocr_version"] = OCRVersion.PPOCRV5

        _engines[lang] = RapidOCR(params=params)
        return _engines[lang]


def warm_langs() -> list[str]:
    return sorted(_engines.keys())


@dataclass
class RenderedPage:
    index: int  # 1-based
    image: Image.Image
    # PDF 텍스트 레이어에서 바로 뽑은 줄. 있으면 OCR을 건너뛴다.
    text_lines: list[TextLine] | None = None


def _downscale(img: Image.Image) -> Image.Image:
    longest = max(img.size)
    if longest <= MAX_SIDE:
        return img
    ratio = MAX_SIDE / longest
    return img.resize(
        (round(img.width * ratio), round(img.height * ratio)), Image.LANCZOS
    )


def load_pages(
    data: bytes, content_type: str | None, force_ocr: bool = False
) -> list[RenderedPage]:
    """업로드된 바이트를 OCR 가능한 RGB 페이지 목록으로 바꾼다."""
    is_pdf = (content_type == "application/pdf") or data[:5] == b"%PDF-"

    if not is_pdf:
        img = Image.open(io.BytesIO(data))
        img.load()
        # EXIF 회전이 반영 안 되면 세로 사진이 눕는다.
        from PIL import ImageOps

        img = ImageOps.exif_transpose(img)
        return [RenderedPage(1, _downscale(img.convert("RGB")))]

    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(data)
    try:
        pages = []
        for i in range(min(len(pdf), MAX_PDF_PAGES)):
            bitmap = pdf[i].render(scale=PDF_RENDER_SCALE)
            image = _downscale(bitmap.to_pil().convert("RGB"))

            # 텍스트 레이어가 있으면 OCR할 이유가 없다. 문서를 닫기 전에 뽑아 둔다.
            # 스캔 PDF에도 쪽 번호 몇 글자는 있을 수 있어서 글자 수로 거른다.
            lines = None
            if not force_ocr and pdftext.has_text_layer(pdf[i]):
                lines = pdftext.extract_lines(pdf[i], image.width, image.height, i + 1, 0)
                lines = lines or None

            pages.append(RenderedPage(i + 1, image, lines))
        return pages
    finally:
        pdf.close()


def _to_data_url(img: Image.Image) -> str:
    """화면 표시용 미리보기. OCR은 원본으로 이미 끝난 뒤라 손실 압축이어도 상관없다."""
    buf = io.BytesIO()
    if img.width * img.height > 1_000_000:
        # 스캔본을 PNG로 담으면 페이지당 2MB가 넘어가서 응답이 눈에 띄게 느려진다.
        img.save(buf, format="JPEG", quality=82, optimize=True)
        mime = "image/jpeg"
    else:
        img.save(buf, format="PNG", optimize=True)
        mime = "image/png"
    return f"data:{mime};base64," + base64.b64encode(buf.getvalue()).decode()


def _polygon_to_bbox(points: list[tuple[float, float]]) -> BBox:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return BBox(x=min(xs), y=min(ys), width=max(xs) - min(xs), height=max(ys) - min(ys))


def run_ocr(
    data: bytes,
    content_type: str | None,
    filename: str,
    lang: LangCode = "korean",
    use_angle_cls: bool = False,
    restore_spacing: bool = True,
    analyze_layout: bool = True,
    force_ocr: bool = False,
) -> OCRResponse:
    """동기 함수 — FastAPI에서는 threadpool로 넘겨서 호출한다.

    use_angle_cls는 기본값이 False다. 각도 분류기(ch_ppocr_mobile_v2.0_cls)는 중국어
    기준으로 학습돼서, 똑바로 놓인 한글 줄을 180도 뒤집힌 것으로 잘못 판정하는 경우가
    있다(예: "부가세(10%)" → "(%OL)|Y∠"). 세로/뒤집힌 스캔을 다룰 때만 켜는 게 낫다.

    restore_spacing은 인식 모델이 흘린 공백을 원본 픽셀 기준으로 되살린다. spacing 모듈 참고.
    analyze_layout은 좌표로 단·행·표를 복원해 읽는 순서를 잡는다. layout 모듈 참고.
    force_ocr은 텍스트 레이어가 있는 PDF도 강제로 OCR한다. 비교용.
    """
    pages = load_pages(data, content_type, force_ocr)
    # 모든 페이지가 텍스트 레이어면 인식 모델을 아예 올리지 않는다 (첫 로딩 5초 절약).
    engine = None if all(p.text_lines is not None for p in pages) else get_engine(lang)

    started = time.perf_counter()
    elapse = np.zeros(3)  # det, cls, rec
    spacing_ms = 0.0
    lines: list[TextLine] = []
    page_infos: list[PageInfo] = []
    page_texts: list[str] = []
    raw_page_texts: list[str] = []

    for page in pages:
        if page.text_lines is not None:
            for line in page.text_lines:
                line.id = len(lines)
                lines.append(line)
            raw_page_texts.append("\n".join(l.text for l in page.text_lines))
            page_infos.append(
                PageInfo(
                    page=page.index,
                    width=page.image.width,
                    height=page.image.height,
                    image_data_url=_to_data_url(page.image),
                    source="pdf_text",
                )
            )
            continue

        array = np.array(page.image)
        # 띄어쓰기 복원에는 글자별 위치가 필요하다.
        result = engine(
            array,
            use_cls=use_angle_cls,
            return_word_box=restore_spacing,
            return_single_char_box=restore_spacing,
        )

        if result.elapse_list:
            # 단계를 건너뛰면 None이 들어온다 (예: 각도 분류 비활성)
            elapse += np.array([e or 0.0 for e in result.elapse_list])

        boxes = result.boxes if result.boxes is not None else []
        txts = result.txts or ()
        scores = result.scores or ()
        word_results = result.word_results or ((),) * len(txts)

        raw_texts_on_page: list[str] = []
        for box, raw_text, score, words in zip(boxes, txts, scores, word_results):
            polygon = [(float(x), float(y)) for x, y in box]

            text = raw_text
            if restore_spacing and words:
                spacing_started = time.perf_counter()
                text = spacing.restore_line(
                    array, raw_text, box, [np.asarray(w[2], dtype=float) for w in words]
                )
                spacing_ms += (time.perf_counter() - spacing_started) * 1000

            lines.append(
                TextLine(
                    id=len(lines),
                    text=text,
                    raw_text=raw_text,
                    spacing_fixed=text != raw_text,
                    confidence=round(float(score), 4),
                    polygon=polygon,
                    bbox=_polygon_to_bbox(polygon),
                    page=page.index,
                )
            )
            raw_texts_on_page.append(raw_text)

        raw_page_texts.append("\n".join(raw_texts_on_page))
        page_infos.append(
            PageInfo(
                page=page.index,
                width=page.image.width,
                height=page.image.height,
                image_data_url=_to_data_url(page.image),
                source="ocr",
            )
        )

    # 레이아웃 분석: 단·행·표를 복원하고 읽는 순서를 매긴다.
    # 괘선은 페이지 이미지에서 뽑는다. 텍스트 레이어 PDF도 렌더된 이미지가 있으니 같다.
    layout_started = time.perf_counter()
    blocks: list[LayoutBlock] = []
    rules_ms = 0.0
    if analyze_layout:
        for page in pages:
            page_lines = [line for line in lines if line.page == page.index]
            if not page_lines:
                continue
            rules_started = time.perf_counter()
            # 괘선 판정의 두께·길이 기준은 글자 높이다 (rules 모듈 설명 참고).
            heights = sorted(line.bbox.height for line in page_lines)
            text_height = heights[len(heights) // 2]
            rulings = rules.detect(page.image, text_height)
            rules_ms += (time.perf_counter() - rules_started) * 1000
            blocks += layout.analyze_page(
                page_lines, page.index, len(blocks), rulings
            )
    layout_ms = (time.perf_counter() - layout_started) * 1000

    by_id = {line.id: line for line in lines}
    if blocks:
        reading_index = 0
        for block in blocks:
            for line_id in block.line_ids:
                by_id[line_id].block_id = block.id
                by_id[line_id].reading_index = reading_index
                reading_index += 1
        ordered = [by_id[i] for block in blocks for i in block.line_ids]
    else:
        ordered = lines

    page_texts = []
    for info in page_infos:
        page_texts.append("\n".join(l.text for l in ordered if l.page == info.page))

    total_ms = (time.perf_counter() - started) * 1000
    return OCRResponse(
        filename=filename,
        lang=lang,
        pages=page_infos,
        lines=lines,
        blocks=blocks,
        full_text="\n\n".join(page_texts).strip(),
        raw_text="\n\n".join(raw_page_texts).strip(),
        markdown=layout.to_markdown(blocks) if blocks else "",
        spacing_fixed_lines=sum(1 for line in lines if line.spacing_fixed),
        quality=quality.assess(lines),
        table_count=sum(1 for block in blocks if block.kind == "table"),
        page_columns=max((b.page_column for b in blocks), default=0) + 1,
        timing=Timing(
            detect_ms=round(elapse[0] * 1000, 1),
            classify_ms=round(elapse[1] * 1000, 1),
            recognize_ms=round(elapse[2] * 1000, 1),
            spacing_ms=round(spacing_ms, 1),
            rules_ms=round(rules_ms, 1),
            layout_ms=round(layout_ms, 1),
            total_ms=round(total_ms, 1),
        ),
        engine=ENGINE_NAME,
    )
