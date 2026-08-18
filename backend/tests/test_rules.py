"""괘선 검출 회귀 테스트.

실행: ./.venv/bin/python tests/test_rules.py

여기 있는 수치는 실제 문서에서 재서 넣은 것이다. 임의로 만든 값이 아니다.
- 연한 1px 선(밝기 234, 배경 255) — 교재 PDF 1쪽의 표 행 구분선
- 두께가 글자 높이의 0.75배인 흐린 선 — 스캔 시뮬레이션이 걸린 거래명세서 샘플
- 두께가 글자 높이의 2.1배인 띠 — 교재 표 머리글의 색 배경
- 짧은 세로획 — 표만 크롭(857x292)에서 세로선 70개를 오검출한 원인

문서: docs/troubleshooting/13-괘선-검출을-행-분할에-쓰면-나빠진다.md
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import rules  # noqa: E402
from app.rules import Ruling  # noqa: E402

WIDTH, HEIGHT = 1200, 800
TEXT_HEIGHT = 20.0


def canvas() -> np.ndarray:
    """흰 종이. 중앙값이 255가 되므로 배경 판정 기준도 255다."""
    return np.full((HEIGHT, WIDTH), 255, dtype=np.uint8)


def draw_h(page: np.ndarray, y: int, x0: int, x1: int, thickness: int = 1, value: int = 234):
    page[y : y + thickness, x0:x1] = value


def draw_v(page: np.ndarray, x: int, y0: int, y1: int, thickness: int = 1, value: int = 234):
    page[y0:y1, x : x + thickness] = value


def test_thin_light_line_is_detected():
    """밝기 234짜리 1px 선. Otsu 이진화로는 배경에 묻혀서 안 잡힌다."""
    page = canvas()
    draw_h(page, 400, 100, 900)

    found = rules.detect(page, TEXT_HEIGHT).horizontal
    assert len(found) == 1, found
    assert abs(found[0].position - 400) <= 2, found[0]


def test_blurred_thick_line_is_detected():
    """스캔본의 괘선은 블러로 두꺼워진다. 거래명세서 샘플이 글자 높이의 0.75배였다."""
    page = canvas()
    draw_h(page, 400, 100, 900, thickness=int(TEXT_HEIGHT * 0.75), value=200)

    found = rules.detect(page, TEXT_HEIGHT).horizontal
    assert len(found) == 1, found


def test_filled_band_is_rejected():
    """표 머리글의 색 배경(글자 높이의 2.1배)은 선이 아니다.

    선으로 치면 띠 한가운데에 행 경계가 생겨서 머리글 글자를 관통한다.
    """
    page = canvas()
    draw_h(page, 380, 100, 900, thickness=int(TEXT_HEIGHT * 2.1), value=234)

    assert rules.detect(page, TEXT_HEIGHT).horizontal == []


def test_short_underline_is_rejected():
    """본문 밑줄·취소선은 짧다. 영역 폭의 15%를 넘어야 선으로 본다."""
    page = canvas()
    draw_h(page, 400, 100, 220)  # 120px = 폭의 10%

    assert rules.detect(page, TEXT_HEIGHT).horizontal == []


def test_character_strokes_are_not_vertical_rules():
    """글자 세로획이 세로 괘선으로 잡히면 안 된다.

    길이 조건을 이미지 변 대비로만 걸었을 때 짧은 크롭(857x292)에서
    세로선 70개가 잡혔고 전부 이것이었다. 그래서 글자 높이 대비 조건을 같이 건다.
    """
    page = canvas()
    for x in range(100, 900, 40):
        draw_v(page, x, 300, 300 + int(TEXT_HEIGHT * 1.5), value=30)

    assert rules.detect(page, TEXT_HEIGHT).vertical == []


def test_broken_line_is_joined():
    """스캔본에서 끊긴 선은 이어 붙여야 길이 조건을 통과한다."""
    page = canvas()
    draw_h(page, 400, 100, 400)
    draw_h(page, 400, 450, 900)  # 50px 끊김

    found = rules.detect(page, TEXT_HEIGHT).horizontal
    assert len(found) == 1, found
    assert found[0].x0 <= 105 and found[0].x1 >= 895, found[0]


def test_crossing_needs_most_of_the_width():
    """영역 폭의 대부분을 덮어야 그 영역을 가로지른 것이다.

    실측에서 진짜 표 행 구분선은 표 폭의 100% 이상이었고,
    본문 밑줄 오검출은 80%와 34%였다. 그 사이에서 가른다.
    """
    full = Ruling(x0=90, y0=399, x1=910, y1=401)
    partial = Ruling(x0=200, y0=449, x1=800, y1=451)  # 표 폭의 75%
    lines = rules.RuledLines(horizontal=[full, partial], vertical=[])

    crossing = lines.crossing(x=100, y=300, width=800, height=200)
    assert crossing == [full], crossing


def test_crossing_respects_the_margin():
    """표 경계 바로 밖의 선(위 테두리)도 그 표의 것으로 본다."""
    border = Ruling(x0=90, y0=294, x1=910, y1=296)
    lines = rules.RuledLines(horizontal=[border], vertical=[])

    assert lines.crossing(100, 300, 800, 200) == []
    assert lines.crossing(100, 300, 800, 200, margin=10) == [border]


if __name__ == "__main__":
    failed = 0
    for name, func in sorted(globals().items()):
        if not name.startswith("test_"):
            continue
        try:
            func()
            print(f"  ok   {name}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {name}: {exc}")
    print("실패 없음" if not failed else f"{failed}개 실패")
    sys.exit(1 if failed else 0)
