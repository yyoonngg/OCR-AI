"""띄어쓰기 복원.

PP-OCR 인식 모델은 글자는 잘 맞히면서 공백을 자주 흘린다
(`결제조건:세금계산서발행일로부터30일이내`, `테헤란로152,8층`).

한국어 띄어쓰기 교정기(Kiwi 등)를 쓰면 문서에 없던 공백까지 넣어버린다.
`거래명세서 → 거래 명세서`, `부가세(10%) → 부가세(10 %)` 처럼 복합명사가 다 쪼개진다.
그래서 언어 모델 대신 **원본 픽셀에 실제로 공백이 있는 자리**만 복원한다.

절차:
1. 검출된 줄 다각형을 똑바로 편 크롭으로 만든다.
2. Otsu 이진화 후 열 방향 잉크 투영으로 글자가 없는 열 구간을 찾는다.
3. 그 구간 중 중앙값의 2배 이상으로 벌어진 곳만 단어 사이 공백으로 본다.
4. 인식 결과의 글자 박스와 대조해 몇 번째 글자 앞인지 정하고 공백을 넣는다.

인식 결과에 이미 있는 공백은 건드리지 않고, 없는 자리에만 추가한다.
"""

from __future__ import annotations

import cv2
import numpy as np

# 단어 사이 공백으로 인정할 최소 폭: 글자 사이 기본 간격의 배수, 그리고 줄 높이 대비 최소 비율.
GAP_RATIO = 2.0
MIN_GAP_TO_HEIGHT = 0.18


def _line_transform(polygon: np.ndarray) -> tuple[np.ndarray, int, int]:
    pts = np.asarray(polygon, dtype=np.float32)
    width = max(np.linalg.norm(pts[0] - pts[1]), np.linalg.norm(pts[3] - pts[2]))
    height = max(np.linalg.norm(pts[0] - pts[3]), np.linalg.norm(pts[1] - pts[2]))
    w, h = max(int(round(width)), 1), max(int(round(height)), 1)
    dst = np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32)
    return cv2.getPerspectiveTransform(pts, dst), w, h


def _to_crop_x(matrix: np.ndarray, points: list) -> np.ndarray:
    arr = np.asarray(points, dtype=np.float32).reshape(-1, 1, 2)
    return cv2.perspectiveTransform(arr, matrix).reshape(-1, 2)[:, 0]


def _blank_runs(crop: np.ndarray) -> list[tuple[int, int]]:
    """글자 획이 하나도 없는 열 구간 [(start, end), ...]."""
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    # 스캔본 음영에 견디도록 Otsu. 글자가 흰색(255)이 되게 반전한다.
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    empty = (binary.sum(axis=0) / 255.0) <= 0.5

    runs: list[tuple[int, int]] = []
    start: int | None = None
    for i, is_empty in enumerate(empty):
        if is_empty and start is None:
            start = i
        elif not is_empty and start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, len(empty)))
    return runs


def restore_line(
    image: np.ndarray, text: str, polygon: np.ndarray, char_boxes: list
) -> str:
    """한 줄의 띄어쓰기를 복원한다. 판단이 서지 않으면 원본을 그대로 돌려준다."""
    if len(char_boxes) < 2 or not text.strip():
        return text

    # 글자 박스 개수가 공백 제외 글자 수와 다르면 대응을 신뢰할 수 없다.
    if len(char_boxes) != len(text.replace(" ", "")):
        return text

    matrix, w, h = _line_transform(polygon)
    crop = cv2.warpPerspective(image, matrix, (w, h))

    # 양끝 여백은 단어 사이 공백이 아니다.
    inner = [(a, b) for a, b in _blank_runs(crop) if a > 0 and b < w]
    if not inner:
        return text

    widths = np.array([b - a for a, b in inner], dtype=float)
    threshold = max(float(np.median(widths)) * GAP_RATIO, h * MIN_GAP_TO_HEIGHT)
    gaps = [(a, b) for (a, b), width in zip(inner, widths) if width >= threshold]
    if not gaps:
        return text

    # 자간을 넓게 준 제목은 모든 글자가 떨어져 있다. 단어 구분이 아니므로 손대지 않는다.
    if len(gaps) >= len(char_boxes) - 1:
        return text

    lefts = _to_crop_x(matrix, [box[0] for box in char_boxes])
    rights = _to_crop_x(matrix, [box[1] for box in char_boxes])
    seams = (rights[:-1] + lefts[1:]) / 2  # 글자 i-1 과 i 사이의 경계

    insert_before = {
        int(np.argmin(np.abs(seams - (a + b) / 2))) + 1 for a, b in gaps
    }

    out: list[str] = []
    char_index = 0
    for ch in text:
        if ch == " ":
            out.append(ch)
            continue
        if char_index in insert_before and out and out[-1] != " ":
            out.append(" ")
        out.append(ch)
        char_index += 1
    return "".join(out)
