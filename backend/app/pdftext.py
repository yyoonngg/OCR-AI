"""PDF 텍스트 레이어 추출 — OCR할 필요가 없는 PDF는 건너뛴다.

전자세금계산서·계약서·보고서처럼 프로그램이 만든 PDF에는 글자가 그대로 들어 있다.
그걸 이미지로 렌더해서 다시 읽는 건 느리기만 하고 부정확하다. 실측:

    텍스트 레이어   3.6ms   "인가된 프로세스, 인가된 시스템만이" / "해야 한다는 원칙"
    OCR           6.77s   "인가된 프로세스 인가된 시스템만이"  / "해야 한다는원칙"

1,862배 느린데 쉼표를 놓치고 띄어쓰기가 붙는다.

## 왜 get_text_range()를 그대로 쓰면 안 되나

pypdfium2가 주는 줄 단위 텍스트는 표의 셀을 한 줄로 합쳐 버린다.

    구분 개념
    기밀성(Confidentiality) 오직 인가된 사람, ... 접근

이러면 레이아웃 분석이 "한 줄 = 한 셀"을 전제로 하는 이상 표를 못 잡는다.
그래서 **문자별 좌표로 줄을 직접 재구성한다.** 가로 간격이 크게 벌어지면 다른 셀로 끊는다.
OCR 검출 박스와 같은 단위가 나오므로 layout 파이프라인을 그대로 태울 수 있다.

## 좌표는 loose 박스를 쓴다

`get_charbox(i)`의 기본값은 글자의 실제 잉크 범위라 글자마다 세로 범위가 다르다.
그러면 `스`의 bottom과 바로 뒤 `,`의 top이 정확히 같아져 세로 겹침이 0이 되고,
문장 한가운데서 줄이 끊긴다. `loose=True`는 폰트 라인박스라 같은 줄 글자가 같은
세로 범위를 갖는다.
"""

from __future__ import annotations

from dataclasses import dataclass

from .schemas import BBox, TextLine

# 임계값은 실제 문서의 문자 간격 분포에서 뽑았다 (높이 대비, 교재 PDF 1쪽 n=1045).
#
#   붙어 있는 글자  중앙값 0.03  99% 0.18  최대 0.30
#   공백 하나       중앙값 0.53  90% 0.69
#   표 셀 경계      2.99 이상
#
# 0.30과 0.53 사이에서 공백을 넣고, 0.69와 2.99 사이에서 셀을 가른다.
SPACE_GAP = 0.35
COLUMN_GAP = 1.5
# 같은 줄로 볼 세로 겹침 비율 (작은 쪽 높이 기준).
ROW_OVERLAP = 0.4
# OCR 검출 박스는 글자 잉크에 여유를 두고 잡힌다. 텍스트 레이어의 박스는 폰트 라인박스라
# 더 타이트해서, 같은 layout 파이프라인에 태우려면 같은 성질을 줘야 한다.
# 이 여유가 없으면 세로 가운데 정렬된 표 라벨이 내용 줄과 같은 밴드로 묶이지 않는다.
# 줄을 다 만든 뒤 bbox에만 적용한다 (조각 병합에 적용하면 다른 행끼리 붙는다).
LINE_PADDING = 0.2

# 페이지당 이보다 글자가 적으면 텍스트 레이어가 없는 것으로 본다.
# 스캔 PDF에도 쪽 번호나 워터마크 몇 글자는 들어 있는 경우가 있다.
MIN_CHARS_PER_PAGE = 40


@dataclass
class _Char:
    text: str
    left: float
    top: float
    right: float
    bottom: float

    @property
    def height(self) -> float:
        return self.bottom - self.top


def page_char_count(page) -> int:
    """이 페이지에 텍스트 레이어가 몇 글자 있는지 (공백 제외)."""
    textpage = page.get_textpage()
    try:
        return len("".join(textpage.get_text_range().split()))
    except Exception:
        return 0


def has_text_layer(page) -> bool:
    return page_char_count(page) >= MIN_CHARS_PER_PAGE


def _read_chars(page, textpage, image_width: int, image_height: int) -> list[_Char]:
    """문자 좌표를 렌더된 이미지 좌표계로 옮긴다.

    PDF 좌표는 원점이 좌하단이고 y가 위로 증가한다. 이미지는 좌상단 원점이다.
    배율은 렌더 설정을 믿지 않고 실제 이미지 크기에서 역산한다 — 축소가 걸렸을 수 있다.
    """
    page_width, page_height = page.get_size()
    if page_width <= 0 or page_height <= 0:
        return []

    sx = image_width / page_width
    sy = image_height / page_height

    text = textpage.get_text_range()
    chars: list[_Char] = []
    for index, ch in enumerate(text):
        if not ch.strip():
            continue  # 공백·개행은 좌표가 무의미하다. 아래에서 간격으로 복원한다.
        try:
            # loose=True는 폰트 메트릭 기반 박스라, 같은 줄 글자가 동일한 세로 범위를 갖는다.
            # 잉크 범위(기본값)를 쓰면 쉼표·마침표가 딴 줄로 떨어져 나간다.
            left, bottom, right, top = textpage.get_charbox(index, loose=True)
        except Exception:
            continue
        if right <= left or top <= bottom:
            continue
        chars.append(
            _Char(
                text=ch,
                left=left * sx,
                top=(page_height - top) * sy,
                right=right * sx,
                bottom=(page_height - bottom) * sy,
            )
        )
    return chars


def _extent(chars: list[_Char]) -> tuple[float, float, float, float]:
    """조각의 (left, top, right, bottom)."""
    return (
        min(c.left for c in chars),
        min(c.top for c in chars),
        max(c.right for c in chars),
        max(c.bottom for c in chars),
    )


def _split_fragments(chars: list[_Char]) -> list[list[_Char]]:
    """문자 순서를 따라가며 조각을 낸다. 애매하면 끊고, 붙이는 건 다음 단계에 맡긴다.

    PDF의 문자 순서는 시각적 순서와 다를 수 있다 — 텍스트 오브젝트 경계에서 좌표가 점프한다.
    그래서 순서만 믿고 이어 붙이면 안 되고, 여기서 낸 조각을 _merge_fragments가
    좌표로 다시 판단한다. 실제 PDF에서 303조각이 170줄로 붙은 적이 있다.
    """
    fragments: list[list[_Char]] = []
    current: list[_Char] = []

    for ch in chars:
        if not current:
            current = [ch]
            continue

        previous = current[-1]
        height = max(previous.height, ch.height, 1.0)
        overlap = min(previous.bottom, ch.bottom) - max(previous.top, ch.top)
        same_row = overlap > min(previous.height, ch.height) * ROW_OVERLAP
        gap = ch.left - previous.right

        if same_row and gap <= height * COLUMN_GAP and ch.left >= previous.left - height:
            current.append(ch)
        else:
            fragments.append(current)
            current = [ch]

    if current:
        fragments.append(current)
    return fragments


def _merge_fragments(fragments: list[list[_Char]]) -> list[list[_Char]]:
    """조각을 좌표만 보고 다시 붙인다.

    조각은 글자 하나보다 대표 높이가 안정적이라, 여기서는 세로 겹침이 믿을 만하다.
    """
    bands: list[list[list[_Char]]] = []

    for fragment in sorted(fragments, key=lambda f: (_extent(f)[1], _extent(f)[0])):
        _, top, _, bottom = _extent(fragment)
        height = bottom - top
        placed = False
        for band in reversed(bands):
            flat = [c for f in band for c in f]
            _, b_top, _, b_bottom = _extent(flat)
            overlap = min(b_bottom, bottom) - max(b_top, top)
            if overlap > min(b_bottom - b_top, height, 1e9) * ROW_OVERLAP:
                band.append(fragment)
                placed = True
                break
        if not placed:
            bands.append([fragment])

    lines: list[list[_Char]] = []
    for band in bands:
        ordered = sorted(band, key=lambda f: _extent(f)[0])
        group = [ordered[0]]
        for fragment in ordered[1:]:
            p_left, p_top, p_right, p_bottom = _extent(group[-1])
            left, top, _, bottom = _extent(fragment)
            height = max(p_bottom - p_top, bottom - top, 1.0)
            if left - p_right <= height * COLUMN_GAP:
                group.append(fragment)
            else:
                lines.append([c for f in group for c in f])
                group = [fragment]
        lines.append([c for f in group for c in f])

    return lines


def _render_text(line: list[_Char]) -> str:
    """글자 사이가 벌어진 곳에 공백을 넣는다. spacing 모듈과 같은 발상인데 좌표가 정확하다."""
    parts = [line[0].text]
    for previous, ch in zip(line, line[1:]):
        height = max(previous.height, ch.height, 1.0)
        if ch.left - previous.right > height * SPACE_GAP:
            parts.append(" ")
        parts.append(ch.text)
    return "".join(parts).strip()


def extract_lines(
    page, image_width: int, image_height: int, page_index: int, first_id: int
) -> list[TextLine]:
    """한 페이지의 텍스트 레이어를 OCR 결과와 같은 모양의 줄 목록으로 만든다."""
    textpage = page.get_textpage()
    chars = _read_chars(page, textpage, image_width, image_height)

    lines: list[TextLine] = []
    for group in _merge_fragments(_split_fragments(chars)):
        group.sort(key=lambda c: c.left)
        text = _render_text(group)
        if not text:
            continue

        x0 = min(c.left for c in group)
        x1 = max(c.right for c in group)
        y0 = min(c.top for c in group)
        y1 = max(c.bottom for c in group)
        # 줄을 다 만든 뒤에만 여유를 준다. 조각 병합 단계에 적용하면 다른 행끼리 붙는다.
        pad = (y1 - y0) * LINE_PADDING
        y0, y1 = y0 - pad, y1 + pad

        lines.append(
            TextLine(
                id=first_id + len(lines),
                text=text,
                raw_text=text,
                spacing_fixed=False,
                # 텍스트 레이어는 추정이 아니라 원본이다. 신뢰도라는 개념이 없다.
                confidence=1.0,
                polygon=[(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
                bbox=BBox(x=x0, y=y0, width=x1 - x0, height=y1 - y0),
                page=page_index,
            )
        )
    return lines
