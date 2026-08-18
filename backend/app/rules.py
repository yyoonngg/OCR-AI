"""괘선 검출 — 표에 실제로 그어진 선을 찾는다.

layout 모듈은 글자 좌표만 보고 표 구조를 추측한다. 그래서 임계값이 계속 늘어났다
(단 폭 비율, 줄 길이 중앙값, 항목 번호 …). 괘선은 추측이 아니라 증거다.
선이 있으면 행 경계가 어디인지 다투지 않아도 된다.

## 왜 Otsu를 쓰지 않나

`spacing.py`는 Otsu 이진화를 쓰는데, 괘선에는 그대로 쓸 수 없다. Otsu는 글자(검정)와
배경(흰색) 사이에서 임계값을 잡으므로, 그 중간 밝기의 연한 선이 배경 쪽으로 떨어진다.
교재 PDF 1쪽의 행 구분선을 재보면 밝기 186~234(배경 255)짜리 1px 선이다. 실측:

    Otsu            거래명세서 1개  교재 1쪽 2개  교재 3쪽 0개  표만 크롭 0개
    배경 대비 -12   거래명세서 5개  교재 1쪽 9개  교재 3쪽 4개  표만 크롭 7개

그래서 "배경보다 조금이라도 어두운가"로 잡는다. 노이즈가 같이 잡히지만
가로로 긴 커널로 opening을 걸면 글자와 함께 사라진다.

## 기준은 이미지 크기가 아니라 글자 높이다

처음에 두께·길이 조건을 이미지 변 대비로 잡았더니 양쪽에서 다 틀렸다.

- 스캔본의 괘선은 블러 때문에 두껍다. 거래명세서 샘플의 1px 선이 실제로는
  10~15px 그라데이션(밝기 193~207, 배경 242)이라 "이미지 높이의 0.5%" 상한에 걸려
  전부 버려졌다
- 표만 크롭(857x292)처럼 짧은 이미지에서는 최소 길이가 43px밖에 안 돼서
  한글 세로획이 그걸 넘었다. 세로선이 70개 잡혔고 전부 오검출이었다

글자 높이를 기준으로 하면 둘 다 해결된다. 괘선은 블러가 걸려도 글자보다 얇고,
글자 획보다 훨씬 길다. 그래서 detect()는 글자 높이를 받는다.

## 괘선으로 행을 나누지는 않는다

처음 목표는 `_rows_of`의 "가장 가까운 앵커에 붙인다" 휴리스틱을 괘선으로 대체하는
것이었다. 재보니 **5개 표 중 4개에서 현재보다 나빠졌다.**

| 표 | 현재 (정답) | 괘선 기반 |
| --- | --- | --- |
| page0 7x2 | 7행 | 6행 — 머리글이 첫 행에 합쳐짐 |
| page2 4x2 | 4행 | 3행 — 같은 증상 |
| table_only 7x2 | 7행 | 6행 — 같은 증상 |
| sample 4x4 | 4행 | 3행 — 같은 증상 |

원인이 전부 같다. **머리글 행은 선이 아니라 색 배경 띠로 구분된다.** 띠는 글자 높이의
2.1배라 두께 조건에서 (옳게) 걸러지고, 그러면 머리글 경계에 괘선이 없다.
게다가 거래명세서의 5x2 표는 괘선이 아예 0개다 — **없다고 표가 아닌 게 아니다.**

그래서 신호를 한 방향으로만 쓴다: **괘선이 표 폭을 가로지르면 그건 확실히 표다.**
없을 때는 아무 말도 하지 않고 기존 좌표 판정에 맡긴다.

## 한계

- 가로선만 있는 표가 흔하다 (교재 1쪽: 가로 8 / 세로 1). 열은 여전히 좌표로 잡아야 한다
- 괘선 없는 표도 많다. 그래서 이건 대체가 아니라 보강이다
- 기울어진 스캔은 가로 커널에 안 걸린다. 선이 대각선이면 조각나서 길이 조건에 미달한다
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

# 배경보다 이만큼 어두우면 선 후보. 연한 회색 괘선(밝기 234, 배경 255)을 살리려고
# Otsu 대신 쓴다. 낮추면 종이 질감·JPEG 링잉까지 들어온다.
DARK_DELTA = 12

# opening 커널 길이 (글자 높이 대비). 이만큼 연속으로 어두워야 살아남는다.
# 한글 글자에는 제 높이의 1.5배짜리 연속 획이 없어서 여기서 지워진다.
SEED_HEIGHTS = 1.5

# 선으로 인정할 최소 길이. 영역 변 대비와 글자 높이 대비를 둘 다 넘어야 한다.
# 변 대비만 쓰면 짧은 크롭에서 글자 획이 통과하고,
# 글자 대비만 쓰면 큰 페이지에서 밑줄·취소선이 통과한다.
MIN_LENGTH_RATIO = 0.15
MIN_LENGTH_HEIGHTS = 3.0

# 이보다 두꺼우면 선이 아니라 채워진 영역이다 (표 머리글의 색 배경 등).
# 교재 표의 파란 머리글 배경은 글자 높이의 2.1배, 블러 걸린 괘선은 0.75배였다.
MAX_THICKNESS_HEIGHTS = 1.0

# 어떤 영역을 "가로지른다"고 볼 최소 겹침 (영역 폭 대비).
# 실측: 진짜 표 행 구분선은 표 폭의 100% 이상, 본문 밑줄 오검출은 80%와 34%였다.
MIN_CROSSING = 0.9

# 글자 높이를 모를 때 쓰는 값. 되도록 실제 값을 넘겨라.
DEFAULT_TEXT_HEIGHT = 20.0

# 조각난 선을 같은 선으로 이을 허용 오차 (두께 방향, 글자 높이 대비).
JOIN_HEIGHTS = 0.3


@dataclass(frozen=True)
class Ruling:
    """선분 하나. 가로선이면 y0 == y1에 가깝고, 세로선이면 x0 == x1에 가깝다."""

    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def position(self) -> float:
        """가로선의 y 또는 세로선의 x (두께 방향 중심)."""
        return (self.y0 + self.y1) / 2 if self.is_horizontal else (self.x0 + self.x1) / 2

    @property
    def is_horizontal(self) -> bool:
        return (self.x1 - self.x0) >= (self.y1 - self.y0)

    @property
    def length(self) -> float:
        return max(self.x1 - self.x0, self.y1 - self.y0)


@dataclass(frozen=True)
class RuledLines:
    horizontal: list[Ruling]
    vertical: list[Ruling]

    def __bool__(self) -> bool:
        return bool(self.horizontal or self.vertical)

    def crossing(
        self, x: float, y: float, width: float, height: float, margin: float = 0.0
    ) -> list[Ruling]:
        """이 사각형을 가로로 가로지르는 가로 괘선.

        영역 폭의 대부분을 덮어야 인정한다. 실측하면 진짜 행 구분선과 오검출이
        여기서 깨끗이 갈린다 (표 폭 대비 진짜 100% 이상 / 밑줄·취소선 80%, 34%).
        """
        if width <= 0:
            return []
        return [
            r
            for r in self.horizontal
            if y - margin <= r.position <= y + height + margin
            and min(r.x1, x + width) - max(r.x0, x) >= width * MIN_CROSSING
        ]


EMPTY = RuledLines(horizontal=[], vertical=[])


def _binarize(gray: np.ndarray) -> np.ndarray:
    """배경보다 어두운 픽셀을 255로. Otsu를 쓰지 않는 이유는 모듈 설명 참고."""
    background = float(np.median(gray))
    return ((gray < background - DARK_DELTA) * 255).astype(np.uint8)


def _segments(mask: np.ndarray, horizontal: bool, text_height: float) -> list[Ruling]:
    """opening으로 남은 픽셀을 선분으로 만든다.

    스캔본에서는 선이 중간에 끊기므로, 커널은 짧게 잡아 조각을 살린 뒤
    같은 위치의 조각을 이어 붙이고 마지막에 전체 길이로 거른다.
    """
    across = mask.shape[1] if horizontal else mask.shape[0]
    seed = max(int(text_height * SEED_HEIGHTS), 8)
    kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (seed, 1) if horizontal else (1, seed)
    )
    opened = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

    thickness_limit = text_height * MAX_THICKNESS_HEIGHTS
    minimum = max(across * MIN_LENGTH_RATIO, text_height * MIN_LENGTH_HEIGHTS)
    tolerance = max(text_height * JOIN_HEIGHTS, 2.0)

    count, _, stats, _ = cv2.connectedComponentsWithStats(opened, 8)
    # 같은 위치(두께 방향)의 조각을 모은다. 끊긴 선을 다시 잇기 위한 것이다.
    groups: list[list[tuple[float, float, float, float]]] = []
    for i in range(1, count):
        x, y, w, h = (float(v) for v in stats[i][:4])
        thick = h if horizontal else w
        if thick > thickness_limit:
            continue

        center = y + h / 2 if horizontal else x + w / 2
        placed = False
        for group in groups:
            centers = [(g[1] + g[3]) / 2 if horizontal else (g[0] + g[2]) / 2 for g in group]
            if abs(sum(centers) / len(centers) - center) <= tolerance:
                group.append((x, y, x + w, y + h))
                placed = True
                break
        if not placed:
            groups.append([(x, y, x + w, y + h)])

    rulings: list[Ruling] = []
    for group in groups:
        x0 = min(g[0] for g in group)
        y0 = min(g[1] for g in group)
        x1 = max(g[2] for g in group)
        y1 = max(g[3] for g in group)
        if max(x1 - x0, y1 - y0) < minimum:
            continue
        rulings.append(Ruling(x0=x0, y0=y0, x1=x1, y1=y1))

    rulings.sort(key=lambda r: r.position)
    return rulings


def detect(image, text_height: float = DEFAULT_TEXT_HEIGHT) -> RuledLines:
    """페이지 이미지에서 가로·세로 괘선을 찾는다.

    좌표계는 입력 이미지와 같다 — TextLine.bbox와 그대로 비교할 수 있다.
    text_height는 그 페이지 글자 높이의 중앙값. 두께·길이 조건의 기준이 된다.
    """
    array = np.asarray(image)
    if array.ndim == 3:
        array = cv2.cvtColor(array, cv2.COLOR_RGB2GRAY)
    if array.ndim != 2 or array.size == 0:
        return EMPTY

    height = max(float(text_height), 4.0)
    mask = _binarize(array)
    return RuledLines(
        horizontal=_segments(mask, True, height),
        vertical=_segments(mask, False, height),
    )
