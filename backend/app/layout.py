"""레이아웃 분석 — 읽는 순서와 표 구조를 좌표에서 복원한다.

검출 결과는 줄 단위 텍스트가 검출 순서대로 나열된 것뿐이라, 2단 편집이면 좌우가 섞이고
표는 셀 관계 없이 흩어진다. 여기서는 추가 모델 없이 bbox 좌표만으로 다음을 만든다.

1. 영역 나누기(XY-cut) — 세로 여백으로 단을 가르고, 안 되면 가로 여백으로 자르고 반복
2. 행(band) 묶기       — 세로로 겹치는 줄들을 한 행으로 묶음
3. 표 영역 찾기        — 셀이 2개 이상인 행이 연달아 나오고 셀 수가 같은 구간
4. 열(column) 나누기   — 표 영역 안에서 x 구간이 겹치는 셀끼리 같은 열로
5. 읽는 순서           — 단 → 위에서 아래 → 표 안에서는 왼쪽에서 오른쪽

세로 여백만 보고 단을 가르면 안 된다. 표의 열 사이도 똑같이 세로 여백이라 표가 통째로
쪼개진다. 반대로 페이지 전체에서만 여백을 찾으면, 가운데 정렬된 제목 한 줄이 단 사이를
가로질러서 2단 편집을 놓친다. 그래서 XY-cut으로 가로/세로를 번갈아 자르되, 세로 절단에는
"단처럼 보이는가" 조건(_vertical_cut 참고)을 붙였다.

여기까지가 좌표만 쓰는 부분이다. 페이지 이미지에서 검출한 괘선(`rules` 모듈)을 넘기면
표 판정에만 추가로 쓴다 — 선이 표를 가로지르면 "그린 표"로 확정한다.
행 나누기까지 괘선에 맡기지는 않는다. 머리글 행이 선이 아니라 색 배경으로 구분되는
문서가 흔해서, 재보니 오히려 나빠졌다 (rules 모듈 설명과 docs/troubleshooting/13번).

레이아웃 분석 모델(PP-Structure 등)을 붙이면 더 정확하겠지만, 정형 문서라면 좌표만으로도
표와 단이 대부분 잡힌다. 한계는 README에 적어뒀다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .rules import RuledLines
from .schemas import BBox, Cell, LayoutBlock, TextLine

# 행으로 묶을 세로 겹침 비율 (작은 쪽 높이 기준)
ROW_OVERLAP = 0.4

# 괘선이 이만큼 이상 표를 가로지르면 "그린 표"로 확정한다. 실측한 분포에서 뽑았다.
#
#   괘선 있는 표   4x4 거래명세서 3개 / 4x2 교재 4개 / 7x2 교재 6개, 6개
#   괘선 없는 표   5x2 거래명세서 0개 / 3x2 합계표 1개 (위 표의 아래 테두리가 걸친 것)
#
# 1~2개로 내리면 안 된다. 상자 하나를 두르면 위아래 테두리만으로 2개가 되어서,
# 네모 친 4지선다가 표로 뒤집힌다.
MIN_RULES_FOR_TABLE = 3
# 표 경계 밖 이만큼까지의 괘선은 그 표의 것으로 본다 (글자 높이 대비).
RULE_MARGIN = 1.0

# --- 세로 절단(단 나누기) 조건 ---
# 여백 폭: 영역 너비 대비, 그리고 줄 높이 대비 둘 다 넘겨야 한다
GUTTER_WIDTH_RATIO = 0.04
GUTTER_HEIGHT_RATIO = 1.5
# 단 하나로 인정하려면 양쪽에 이만큼은 줄이 있어야 한다
MIN_LINES_PER_COLUMN = 3
# 각 단이 영역 높이의 이만큼은 차지해야 한다. 표의 열은 이 조건에서 자주 걸린다
MIN_COLUMN_HEIGHT_COVERAGE = 0.6
# 각 단의 줄 길이(중앙값)가 이보다 짧으면 본문 단이 아니라 표의 열로 본다
MIN_COLUMN_TEXT_LENGTH = 8
# 단 폭이 서로 이 배수 넘게 차이 나면 2단 편집이 아니라 표의 열로 본다.
# 2단 편집은 설계상 단 폭이 거의 같은 반면, 표는 라벨 열이 내용 열보다 훨씬 좁다.
MAX_COLUMN_WIDTH_RATIO = 1.8
# 단 사이 여백을 가로질러도 되는 줄의 비율 (가운데 정렬된 제목 등)
MAX_GUTTER_CROSSING = 0.08
# 가로지르는 줄을 구분선으로 인정할 최소 너비 (영역 너비 대비)
MIN_SPANNING_WIDTH = 0.2

# --- 가로 절단 조건 ---
# 줄 높이 대비 이만큼 벌어지면 다른 영역으로 본다. 문단 안 줄 간격보다는 커야 한다
MIN_ROW_GAP = 1.2

# 첫 행이 아랫줄들보다 이 비율 이하로 짧으면 머리글로 본다
HEADER_LENGTH_RATIO = 0.5

# 4지선다 판별: 칸 길이 상한, 그리고 "서로 다른 값 / 전체 칸 수"의 상한
CHOICE_MAX_LENGTH = 12
CHOICE_REPEAT_RATIO = 0.6

# 문단으로 이어 붙일 최대 줄 간격 (줄 높이 대비)
PARAGRAPH_GAP = 1.6
# 같은 문단으로 볼 왼쪽 정렬 허용 오차 (줄 높이 대비)
PARAGRAPH_INDENT = 1.2


@dataclass
class _Band:
    """세로로 겹치는 줄들의 묶음 = 시각적인 한 행."""

    lines: list[TextLine] = field(default_factory=list)

    @property
    def top(self) -> float:
        return min(line.bbox.y for line in self.lines)

    @property
    def bottom(self) -> float:
        return max(line.bbox.y + line.bbox.height for line in self.lines)

    @property
    def height(self) -> float:
        return max(line.bbox.height for line in self.lines)


def _bbox_of(lines: list[TextLine]) -> BBox:
    x0 = min(line.bbox.x for line in lines)
    y0 = min(line.bbox.y for line in lines)
    x1 = max(line.bbox.x + line.bbox.width for line in lines)
    y1 = max(line.bbox.y + line.bbox.height for line in lines)
    return BBox(x=x0, y=y0, width=x1 - x0, height=y1 - y0)


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[len(ordered) // 2] if ordered else 0.0


def _line_height(lines: list[TextLine]) -> float:
    return _median([line.bbox.height for line in lines]) or 1.0


def _free_runs(
    intervals: list[tuple[float, float]], minimum: float
) -> list[tuple[float, float]]:
    """구간들이 덮지 않는 빈 자리 중 minimum 이상으로 벌어진 곳."""
    merged: list[list[float]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [
        (a[1], b[0]) for a, b in zip(merged, merged[1:]) if b[0] - a[1] >= minimum
    ]


def _gutter_positions(lines: list[TextLine], minimum: float, max_cross: int) -> list[float]:
    """단 사이 여백의 x 위치.

    가로지르는 줄이 max_cross개 이하면 여백으로 친다. 가운데 정렬된 제목 한 줄 때문에
    2단을 놓치는 걸 막기 위한 것이다.
    """
    left = int(min(line.bbox.x for line in lines))
    right = int(max(line.bbox.x + line.bbox.width for line in lines))
    if right <= left:
        return []

    counts = [0] * (right - left + 2)
    for line in lines:
        start = int(line.bbox.x) - left
        end = int(line.bbox.x + line.bbox.width) - left
        for x in range(max(start, 0), min(end, len(counts) - 1)):
            counts[x] += 1

    cuts: list[float] = []
    x = 0
    while x < len(counts) - 1:
        if counts[x] > max_cross:
            x += 1
            continue
        start = x
        while x < len(counts) - 1 and counts[x] <= max_cross:
            x += 1
        # 영역 바깥 여백은 단 구분이 아니다
        if start > 0 and x < len(counts) - 1 and x - start >= minimum:
            cuts.append(left + (start + x) / 2)
    return cuts


def _column_layout(lines: list[TextLine]) -> list[tuple[list[TextLine], int]] | None:
    """영역을 단(段)으로 나누고 읽는 순서대로 (줄 묶음, 단 번호)를 돌려준다.

    표의 열 사이도 세로 여백이라, 아래 조건을 다 통과할 때만 단으로 인정한다.
    - 각 단에 줄이 충분히 있고
    - 각 단이 영역 높이의 대부분을 차지하며 (표의 열은 대개 여기서 걸린다)
    - 각 단의 줄이 본문처럼 충분히 길다 (수량·금액 같은 짧은 열은 여기서 걸린다)

    단 사이를 가로지르는 줄(가운데 정렬된 제목 등)은 구분선으로 따로 빼서,
    그 위아래로 단을 나눠 읽는다.
    """
    if len(lines) < MIN_LINES_PER_COLUMN * 2:
        return None

    left = min(line.bbox.x for line in lines)
    right = max(line.bbox.x + line.bbox.width for line in lines)
    top = min(line.bbox.y for line in lines)
    bottom = max(line.bbox.y + line.bbox.height for line in lines)
    region_width, region_height = right - left, bottom - top
    if region_width <= 0 or region_height <= 0:
        return None

    minimum = max(
        region_width * GUTTER_WIDTH_RATIO, _line_height(lines) * GUTTER_HEIGHT_RATIO
    )
    max_cross = max(1, int(len(lines) * MAX_GUTTER_CROSSING))
    cuts = _gutter_positions(lines, minimum, max_cross)
    if not cuts:
        return None

    def crosses(line: TextLine) -> bool:
        return any(line.bbox.x < cut < line.bbox.x + line.bbox.width for cut in cuts)

    spanning = [line for line in lines if crosses(line)]
    rest = [line for line in lines if not crosses(line)]
    if len(spanning) > max_cross:
        return None
    # 좁은 줄이 우연히 걸친 것이라면 구분선으로 볼 수 없다.
    if any(line.bbox.width < region_width * MIN_SPANNING_WIDTH for line in spanning):
        return None

    bounds = [float("-inf"), *cuts, float("inf")]
    groups: list[list[TextLine]] = []
    for lo, hi in zip(bounds, bounds[1:]):
        group = [line for line in rest if lo <= line.bbox.x + line.bbox.width / 2 < hi]
        if not group:
            return None
        groups.append(group)
    if len(groups) < 2:
        return None

    widths: list[float] = []
    for group in groups:
        if len(group) < MIN_LINES_PER_COLUMN:
            return None
        extent = max(l.bbox.y + l.bbox.height for l in group) - min(l.bbox.y for l in group)
        if extent < region_height * MIN_COLUMN_HEIGHT_COVERAGE:
            return None
        if _median([len(l.text.strip()) for l in group]) < MIN_COLUMN_TEXT_LENGTH:
            return None
        widths.append(
            max(l.bbox.x + l.bbox.width for l in group) - min(l.bbox.x for l in group)
        )

    # 표의 라벨 열은 글자가 길어도("기밀성(Confidentiality)") 내용 열보다 훨씬 좁다.
    if min(widths) <= 0 or max(widths) / min(widths) > MAX_COLUMN_WIDTH_RATIO:
        return None

    # 구분선을 경계로 위아래를 나누고, 각 구간 안에서는 왼쪽 단부터 읽는다.
    regions: list[tuple[list[TextLine], int]] = []
    edges = [*sorted(line.bbox.y for line in spanning), float("inf")]
    start = float("-inf")
    for edge in edges:
        for index, group in enumerate(groups):
            slice_lines = [l for l in group if start <= l.bbox.y < edge]
            if slice_lines:
                regions.append((slice_lines, index))
        divider = [l for l in spanning if l.bbox.y == edge]
        if divider:
            regions.append((divider, 0))
        start = edge
    return regions


def _horizontal_cut(lines: list[TextLine]) -> list[list[TextLine]] | None:
    """문단 사이보다 확실히 넓은 가로 여백에서 영역을 위아래로 자른다."""
    if len(lines) < 2:
        return None

    minimum = _line_height(lines) * MIN_ROW_GAP
    breaks = _free_runs(
        [(line.bbox.y, line.bbox.y + line.bbox.height) for line in lines], minimum
    )
    if not breaks:
        return None

    bounds = [float("-inf"), *((a + b) / 2 for a, b in breaks), float("inf")]
    groups: list[list[TextLine]] = []
    for lo, hi in zip(bounds, bounds[1:]):
        group = [line for line in lines if lo <= line.bbox.y + line.bbox.height / 2 < hi]
        if group:
            groups.append(group)
    return groups if len(groups) >= 2 else None


def _segment(
    lines: list[TextLine], column: int, allow_vertical: bool = True
) -> list[tuple[list[TextLine], int]]:
    """XY-cut. 읽는 순서대로 정렬된 (영역, 단 번호) 목록을 돌려준다."""
    if len(lines) < 2:
        return [(lines, column)]

    if allow_vertical:
        parts = _column_layout(lines)
        if parts:
            regions: list[tuple[list[TextLine], int]] = []
            for part, offset in parts:
                # 방금 세로로 잘랐으니 같은 자리에서 또 자르지 않도록 한 단계 막는다.
                regions += _segment(part, column + offset, allow_vertical=False)
            return regions

    parts = _horizontal_cut(lines)
    if parts:
        regions = []
        for part in parts:
            regions += _segment(part, column, allow_vertical=True)
        return regions

    return [(lines, column)]


def _group_bands(lines: list[TextLine]) -> list[_Band]:
    """세로로 겹치는 줄들을 한 행으로 묶는다."""
    bands: list[_Band] = []
    for line in sorted(lines, key=lambda l: (l.bbox.y, l.bbox.x)):
        top, bottom = line.bbox.y, line.bbox.y + line.bbox.height
        placed = False
        for band in reversed(bands):
            overlap = min(bottom, band.bottom) - max(top, band.top)
            if overlap > ROW_OVERLAP * min(line.bbox.height, band.height):
                band.lines.append(line)
                placed = True
                break
        if not placed:
            bands.append(_Band([line]))

    for band in bands:
        band.lines.sort(key=lambda l: l.bbox.x)
    return bands


def _columns_of(bands: list[_Band]) -> list[tuple[float, float]]:
    """표 영역 안에서 x 구간이 겹치는 셀끼리 하나의 열로 합친다."""
    spans = sorted(
        (line.bbox.x, line.bbox.x + line.bbox.width)
        for band in bands
        for line in band.lines
    )
    merged: list[list[float]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(a, b) for a, b in merged]


def _column_index(line: TextLine, columns: list[tuple[float, float]]) -> int:
    """겹치는 폭이 가장 큰 열에 셀을 배정한다."""
    left, right = line.bbox.x, line.bbox.x + line.bbox.width
    best, best_overlap = 0, -1.0
    for i, (a, b) in enumerate(columns):
        overlap = min(right, b) - max(left, a)
        if overlap > best_overlap:
            best, best_overlap = i, overlap
    return best


def _merge_spans(spans: list[tuple[float, float]]) -> list[list[float]]:
    merged: list[list[float]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def _try_add(columns: list[list[float]], band: _Band) -> list[list[float]] | None:
    """행 하나를 현재 열 구조에 얹어 본다. 구조가 깨지면 None.

    셀 내용이 두 줄로 넘어가는 경우가 흔해서(예: "오직 인가된 사람 ... 접근 / 해야 한다는 원칙")
    행마다 줄 개수가 달라진다. 그래서 줄 개수가 아니라 **열 구조가 유지되는지**로 판단한다.
    한 열에 여러 줄이 배정돼도 가로로 겹치면 줄바꿈된 같은 셀이고,
    가로로 떨어져 있으면 새로운 열이 생긴 것이므로 표가 거기서 바뀐 것이다.
    """
    trial = [list(column) for column in columns]
    buckets: dict[int, list[TextLine]] = {}

    for line in sorted(band.lines, key=lambda l: l.bbox.x):
        left, right = line.bbox.x, line.bbox.x + line.bbox.width
        best, best_overlap = -1, 0.0
        for index, (lo, hi) in enumerate(trial):
            overlap = min(right, hi) - max(left, lo)
            if overlap > best_overlap:
                best, best_overlap = index, overlap

        if best < 0:
            trial.append([left, right])
            trial.sort(key=lambda c: c[0])
            # 열을 새로 만들면 인덱스가 밀리므로 배정을 다시 한다.
            return _try_add(trial, band)

        trial[best][0] = min(trial[best][0], left)
        trial[best][1] = max(trial[best][1], right)
        buckets.setdefault(best, []).append(line)

    for group in buckets.values():
        for previous, current in zip(group, group[1:]):
            # 가로로 떨어진 두 줄이 같은 열에 들어갔다 = 열 구조가 바뀌었다
            if previous.bbox.x + previous.bbox.width <= current.bbox.x:
                return None

    if 0 not in buckets:
        # 첫 열이 비었다. 셀 하나가 줄바꿈된 것이면 열도 하나뿐이다.
        # 여러 열에 걸쳐 있으면 다른 표가 시작된 것이다 (예: 품목 표 아래의 합계 표).
        if len(buckets) > 1:
            return None
    elif len(band.lines) == 1:
        # 표 뒤에 이어지는 본문 문단이 딸려 들어오지 않게 한다.
        return None

    return trial


def _table_runs(bands: list[_Band]) -> list[tuple[int, int]]:
    """표로 볼 구간 [(start, end), ...]."""
    if not bands:
        return []

    height = _line_height([line for band in bands for line in band.lines])
    runs: list[tuple[int, int]] = []

    start = 0
    while start < len(bands):
        columns = _merge_spans(
            [(l.bbox.x, l.bbox.x + l.bbox.width) for l in bands[start].lines]
        )
        if len(columns) < 2:
            start += 1
            continue

        end = start + 1
        while end < len(bands):
            # 위 행과 멀리 떨어져 있으면 다른 덩어리다.
            if bands[end].top - bands[end - 1].bottom > height * MIN_ROW_GAP:
                break
            grown = _try_add(columns, bands[end])
            if grown is None:
                break
            columns = grown
            end += 1

        if end - start >= 2:
            runs.append((start, end))
            start = end
        else:
            start += 1
    return runs


_NUMERIC = re.compile(r"^[\d,.\s%()\-₩원개]+$")

# 항목 번호: ① ② ③ / ㉠ / 1) 1. (1) / 가) 가.
# 뒤에 내용이 이어져야 한다. 번호만 있는 칸("1", "2")은 표의 번호 열일 수 있다.
_LIST_MARKER = re.compile(r"^(?:[①-⑳㉑-㊿㈀-㈞]|\(?\d{1,2}[.)]|[가-힣][.)])\s*\S")


def _looks_numeric(text: str) -> bool:
    return bool(text.strip()) and bool(_NUMERIC.match(text.strip()))


def _detect_header(grid: list[list[str]]) -> bool:
    """머리글 행이 있는지 판단.

    두 가지 신호를 본다.
    1. "수량 / 1 / 40 / 1"처럼 첫 칸만 글자이고 아래는 숫자로 채워진 열이 있다
    2. "구분 / 기밀성(Confidentiality) / 무결성(Integrity) ..."처럼 첫 행이 모든 열에서
       아랫줄들보다 눈에 띄게 짧다

    "공급가액 | 15,600,000"처럼 첫 행부터 값이 들어 있는 항목-값 표는 둘 다 걸리지 않는다.
    """
    if len(grid) < 2:
        return False
    header, body = grid[0], grid[1:]

    for c in range(len(header)):
        if _looks_numeric(header[c]):
            continue
        below = [row[c] for row in body if row[c].strip()]
        if below and sum(_looks_numeric(v) for v in below) >= len(below) / 2:
            return True

    if all(cell.strip() for cell in header):
        shorter = 0
        for c in range(len(header)):
            below = [len(row[c].strip()) for row in body if row[c].strip()]
            if below and len(header[c].strip()) <= _median(below) * HEADER_LENGTH_RATIO:
                shorter += 1
        if shorter == len(header):
            return True
    return False


def _gap_between(a: _Band, b: _Band) -> float:
    return max(a.top - b.bottom, b.top - a.bottom, 0.0)


def _rows_of(bands: list[_Band], columns: list[tuple[float, float]]) -> list[list[TextLine]]:
    """밴드들을 실제 표의 행으로 묶는다.

    셀 내용이 두 줄 이상으로 넘어가면 그 줄들은 별도 밴드가 된다. 게다가 항목 이름이 세로
    가운데 정렬이면 이름이 첫 줄이 아니라 가운데 줄과 겹쳐서, 이어지는 줄이 행보다 위에
    올 수도 있고 아래에 올 수도 있다.

    그래서 첫 열을 차지하는 밴드만 행으로 보고, 나머지는 세로로 더 가까운 행에 붙인다.
    """
    anchors = [
        i
        for i, band in enumerate(bands)
        if any(_column_index(line, columns) == 0 for line in band.lines)
    ]
    if not anchors:
        return [list(band.lines) for band in bands]

    rows: list[list[TextLine]] = [list(bands[i].lines) for i in anchors]
    for i, band in enumerate(bands):
        if i in anchors:
            continue
        nearest = min(anchors, key=lambda a: _gap_between(band, bands[a]))
        rows[anchors.index(nearest)] += band.lines
    return rows


def _has_marker_column(table: LayoutBlock) -> bool:
    """첫 열에 항목 번호(①②③④ 등)가 붙어 있는가.

    실제 표의 첫 열(`구분`·`품목`·`단계`·`공급가액`)에는 이런 번호가 없다.
    첫 행은 `(가) (나) (다)`처럼 번호 없는 라벨 줄일 수 있어서 예외로 둔다.
    """
    firsts = [""] * table.rows
    for cell in table.cells:
        if cell.column == 0:
            firsts[cell.row] = cell.text.strip()

    marked = [bool(_LIST_MARKER.match(text)) for text in firsts]
    return sum(marked) >= 2 and all(marked[1:])


def _answers_to_question(table: LayoutBlock, previous: LayoutBlock | None) -> bool:
    """항목 번호가 인식되지 않았을 때 쓰는 보조 신호.

    ①②③④는 글자가 작아서 검출을 놓치는 일이 잦다. 그때도 4지선다는 이렇게 생겼다.

    - 바로 앞 블록에 물음표로 끝나는 문장이 있다 (문제)
    - 칸이 전부 짧다
    - 같은 값이 자리만 바꿔 반복된다 (`무결성`·`가용성`·`기밀성` 15칸에 6종류)

    마지막 조건이 핵심이다. 실제 표는 칸마다 값이 달라서 반복률이 낮다.
    "숫자 칸이 없을 것"은 넣지 않았다. `(나)`가 `(4)`로 오인식되는 것만으로 조건이
    무너지고, 답이 숫자인 문제도 흔하다.
    """
    if previous is None or previous.kind != "text" or table.rows < 3:
        return False
    if not any(line.rstrip().endswith(("?", "？")) for line in previous.text.splitlines()):
        return False

    texts = [cell.text.strip() for cell in table.cells if cell.text.strip()]
    if not texts or any(len(text) > CHOICE_MAX_LENGTH for text in texts):
        return False
    return len(set(texts)) <= len(texts) * CHOICE_REPEAT_RATIO


def _is_choice_list(table: LayoutBlock, previous: LayoutBlock | None) -> bool:
    """표처럼 격자로 놓였지만 실은 번호 매긴 목록(4지선다 등)인지 판단.

    4지선다는 좌표만 보면 완전한 격자다. `(가) (나) (다)` 머리줄에 `① 무결성 | 가용성 | 기밀성`
    같은 행이 이어지니 기하로는 표와 구분되지 않는다. 내용에서 신호를 찾아야 한다.
    """
    return _has_marker_column(table) or _answers_to_question(table, previous)


def _make_table(block_id: int, page: int, column: int, bands: list[_Band]) -> LayoutBlock:
    columns = _columns_of(bands)
    rows = _rows_of(bands, columns)

    cells: list[Cell] = []
    for r, row_lines in enumerate(rows):
        buckets: dict[int, list[TextLine]] = {}
        for line in row_lines:
            buckets.setdefault(_column_index(line, columns), []).append(line)
        for c, group in sorted(buckets.items()):
            # 줄바꿈된 셀은 위에서 아래로 읽어야 원래 문장이 된다. 다만 검출기가 한 줄을
            # 둘로 쪼개는 경우가 있어서, y가 조금 차이 나도 같은 줄이면 왼쪽부터 읽는다.
            tolerance = max(_line_height(group) * 0.7, 1.0)
            group.sort(key=lambda l: (int(l.bbox.y / tolerance), l.bbox.x))
            cells.append(
                Cell(
                    row=r,
                    column=c,
                    text=" ".join(line.text for line in group),
                    line_ids=[line.id for line in group],
                    bbox=_bbox_of(group),
                )
            )

    grid = [["" for _ in columns] for _ in rows]
    for cell in cells:
        grid[cell.row][cell.column] = cell.text

    # 읽는 순서는 표 구조를 따른다: 행 위에서 아래로, 행 안에서는 왼쪽 셀부터.
    ordered_ids = [line_id for cell in cells for line_id in cell.line_ids]
    lines = [line for band in bands for line in band.lines]
    return LayoutBlock(
        id=block_id,
        kind="table",
        page=page,
        page_column=column,
        bbox=_bbox_of(lines),
        text="",
        line_ids=ordered_ids,
        rows=len(rows),
        columns=len(columns),
        has_header=_detect_header(grid),
        cells=cells,
    )


def _make_text(block_id: int, page: int, column: int, bands: list[_Band]) -> LayoutBlock:
    lines = [line for band in bands for line in band.lines]
    return LayoutBlock(
        id=block_id,
        kind="text",
        page=page,
        page_column=column,
        bbox=_bbox_of(lines),
        text="\n".join(" ".join(line.text for line in band.lines) for band in bands),
        line_ids=[line.id for line in lines],
    )


def _merge_paragraph(previous: _Band, current: _Band) -> bool:
    """줄 간격과 왼쪽 정렬이 비슷하면 같은 문단으로 이어 붙인다."""
    height = max(previous.height, current.height)
    if current.top - previous.bottom > PARAGRAPH_GAP * height:
        return False
    left_shift = abs(current.lines[0].bbox.x - previous.lines[0].bbox.x)
    return left_shift <= PARAGRAPH_INDENT * height


def _is_ruled(bbox: BBox, rulings: RuledLines | None, height: float) -> bool:
    """이 영역에 실제로 그어진 가로 괘선이 충분히 있는가.

    있으면 "그린 표"다. 없다고 표가 아닌 건 아니다 — 거래명세서의 항목 표는
    괘선이 0개다. 그래서 이 신호는 확정에만 쓰고 부정에는 쓰지 않는다.
    """
    if rulings is None:
        return False
    crossing = rulings.crossing(
        bbox.x, bbox.y, bbox.width, bbox.height, height * RULE_MARGIN
    )
    return len(crossing) >= MIN_RULES_FOR_TABLE


def analyze_page(
    lines: list[TextLine],
    page: int,
    next_block_id: int,
    rulings: RuledLines | None = None,
) -> list[LayoutBlock]:
    """한 페이지의 줄들을 읽는 순서대로 정렬된 레이아웃 블록으로 바꾼다.

    rulings는 페이지 이미지에서 검출한 괘선(rules 모듈). 없으면 좌표만으로 판단한다.
    """
    if not lines:
        return []

    blocks: list[LayoutBlock] = []
    block_id = next_block_id
    page_height = _line_height(lines)

    for group, column in _segment(lines, 0):
        bands = _group_bands(group)
        table_span: dict[int, tuple[int, int]] = {}  # 밴드 인덱스 → 소속 표 구간
        for start, end in _table_runs(bands):
            for i in range(start, end):
                table_span[i] = (start, end)

        i = 0
        while i < len(bands):
            if i in table_span:
                start, end = table_span[i]
                table = _make_table(block_id, page, column, bands[start:end])
                # 줄바꿈된 줄을 행에 합치고 나면 한 행짜리로 쪼그라들 수 있다.
                # 가로로 늘어선 도표 라벨 같은 것들인데, 표로 볼 수 없다.
                # 번호 매긴 목록(4지선다)도 격자일 뿐 표가 아니다.
                #
                # 단, 괘선이 그어져 있으면 그 판정을 뒤집는다. 4지선다 판정은 내용
                # 신호(항목 번호, 앞 블록의 물음표)에 기대는 약한 근거라 실제 표를
                # 잘못 내치는 경우가 있는데, 그려진 선은 그보다 확실한 증거다.
                previous = blocks[-1] if blocks else None
                if table.rows >= 2 and table.columns >= 2 and (
                    _is_ruled(table.bbox, rulings, page_height)
                    or not _is_choice_list(table, previous)
                ):
                    blocks.append(table)
                else:
                    blocks.append(_make_text(block_id, page, column, bands[start:end]))
                block_id += 1
                i = end
                continue

            # 표가 아닌 줄은 문단 단위로 묶는다.
            chunk = [bands[i]]
            j = i + 1
            while j < len(bands) and j not in table_span and _merge_paragraph(chunk[-1], bands[j]):
                chunk.append(bands[j])
                j += 1
            blocks.append(_make_text(block_id, page, column, chunk))
            block_id += 1
            i = j

    return blocks


def to_markdown(blocks: list[LayoutBlock]) -> str:
    """레이아웃 블록을 마크다운으로. 표는 파이프 표로 나간다."""
    parts: list[str] = []
    previous_page = blocks[0].page if blocks else 1
    for block in blocks:
        if block.page != previous_page:
            parts.append("---")
            previous_page = block.page

        if block.kind == "text":
            parts.append(block.text)
            continue

        grid = [["" for _ in range(block.columns)] for _ in range(block.rows)]
        for cell in block.cells:
            grid[cell.row][cell.column] = cell.text.replace("|", "\\|")

        # 마크다운 표는 머리글 행이 필수라, 머리글이 없는 표는 빈 행을 넣는다.
        header = grid[0] if block.has_header else ["" for _ in range(block.columns)]
        body = grid[1:] if block.has_header else grid

        rows = ["| " + " | ".join(header) + " |"]
        rows.append("| " + " | ".join("---" for _ in header) + " |")
        rows += ["| " + " | ".join(row) + " |" for row in body]
        parts.append("\n".join(rows))

    return "\n\n".join(part for part in parts if part.strip())
