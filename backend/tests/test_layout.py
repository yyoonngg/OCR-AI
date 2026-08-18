"""레이아웃 분석 회귀 테스트.

이미지 없이 좌표만 만들어서 돌린다. 실행:

    ./.venv/bin/python tests/test_layout.py

여기 있는 것들은 실제로 한 번씩 깨졌던 케이스다.
- 표의 두 열이 2단 편집으로 잘못 잘림
- 셀 내용이 줄바꿈되면 표가 거기서 끊김
- 항목 이름이 세로 가운데 정렬이라 이어지는 줄이 행 위로 감
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import layout  # noqa: E402
from app.rules import RuledLines, Ruling  # noqa: E402
from app.schemas import BBox, TextLine  # noqa: E402

_next_id = 0


def line(text: str, x: float, y: float, width: float, height: float = 20) -> TextLine:
    global _next_id
    _next_id += 1
    return TextLine(
        id=_next_id,
        text=text,
        raw_text=text,
        spacing_fixed=False,
        confidence=0.99,
        polygon=[(x, y), (x + width, y), (x + width, y + height), (x, y + height)],
        bbox=BBox(x=x, y=y, width=width, height=height),
        page=1,
    )


def tables(blocks):
    return [(b.rows, b.columns) for b in blocks if b.kind == "table"]


def test_label_table_is_not_split_into_page_columns():
    """라벨 열이 길어도(기밀성(Confidentiality)) 2단 편집으로 잘리면 안 된다."""
    labels = ["구분", "기밀성(Confidentiality)", "무결성(Integrity)", "가용성(Availability)"]
    lines = []
    for i, label in enumerate(labels):
        y = 100 + i * 40
        lines.append(line(label, 40, y, 160))
        lines.append(line("정보의 내용이 불법적으로 생성되거나 변경되지 않도록" * 2, 260, y, 700))

    assert layout._column_layout(lines) is None, "표가 단으로 잘렸다"
    blocks = layout.analyze_page(lines, 1, 0)
    assert tables(blocks) == [(4, 2)], tables(blocks)


def test_real_two_column_layout_is_split():
    """폭이 비슷한 진짜 2단 편집은 그대로 나눠야 한다."""
    lines = []
    for i in range(8):
        y = 100 + i * 40
        lines.append(line(f"왼쪽 단의 본문 {i}번째 줄입니다", 40, y, 420))
        lines.append(line(f"오른쪽 단의 본문 {i}번째 줄입니다", 520, y, 420))

    blocks = layout.analyze_page(lines, 1, 0)
    assert {b.page_column for b in blocks} == {0, 1}, "2단을 놓쳤다"


def test_wrapped_cell_keeps_table_together():
    """셀 내용이 두 줄로 넘어가도 표가 끊기면 안 된다."""
    lines = [
        line("구분", 40, 100, 60),
        line("개념", 260, 100, 60),
        # 이름이 세로 가운데 정렬 → 이어지는 줄이 이름보다 위에 온다
        line("오직 인가된 사람, 인가된 프로세스만이 접근", 260, 140, 700),
        line("기밀성(Confidentiality)", 40, 162, 160),
        line("해야 한다는 원칙", 260, 168, 200),
        line("무결성(Integrity)", 40, 210, 140),
        line("정보의 내용이 변경되지 않도록 보호되는 성질", 260, 210, 700),
    ]

    blocks = layout.analyze_page(lines, 1, 0)
    assert tables(blocks) == [(3, 2)], tables(blocks)

    table = next(b for b in blocks if b.kind == "table")
    cell = next(c for c in table.cells if c.row == 1 and c.column == 1)
    assert cell.text == "오직 인가된 사람, 인가된 프로세스만이 접근 해야 한다는 원칙", cell.text
    label = next(c for c in table.cells if c.row == 1 and c.column == 0)
    assert label.text == "기밀성(Confidentiality)", label.text


def test_new_table_starts_when_first_column_empty():
    """첫 열이 비고 여러 열에 걸친 행은 줄바꿈이 아니라 새 표다."""
    lines = [
        line("품목", 40, 100, 60),
        line("수량", 400, 100, 60),
        line("금액", 700, 100, 60),
        line("문서 OCR 엔진 라이선스", 40, 140, 300),
        line("1", 400, 140, 20),
        line("8,400,000", 700, 140, 120),
        line("온프레미스 설치 및 교육", 40, 180, 300),
        line("1", 400, 180, 20),
        line("1,200,000", 700, 180, 120),
        # 합계 표: 첫 열이 비어 있고 두 열에 걸침
        line("공급가액", 400, 240, 100),
        line("9,600,000", 700, 240, 120),
        line("합계금액", 400, 280, 100),
        line("10,560,000", 700, 280, 130),
    ]

    blocks = layout.analyze_page(lines, 1, 0)
    assert tables(blocks) == [(3, 3), (2, 2)], tables(blocks)


def test_numbered_choices_are_not_a_table():
    """4지선다는 격자로 놓였지만 표가 아니다."""
    lines = [
        line("(가)", 60, 100, 50),
        line("(나)", 200, 100, 50),
        line("(다)", 340, 100, 50),
    ]
    for i, (a, b, c) in enumerate(
        [("무결성", "가용성", "기밀성"), ("무결성", "기밀성", "가용성"),
         ("기밀성", "가용성", "무결성"), ("기밀성", "무결성", "가용성")]
    ):
        y = 140 + i * 30
        lines.append(line(f"{'①②③④'[i]} {a}", 40, y, 90))
        lines.append(line(b, 200, y, 60))
        lines.append(line(c, 340, y, 60))

    blocks = layout.analyze_page(lines, 1, 0)
    assert tables(blocks) == [], tables(blocks)
    assert "① 무결성 가용성 기밀성" in blocks[0].text, blocks[0].text


def _choice_grid(marked: bool, values, question: str | None):
    lines = []
    if question:
        lines.append(line(question, 40, 100, 600))
    lines += [line("(가)", 60, 180, 50), line("(나)", 200, 180, 50), line("(다)", 340, 180, 50)]
    for i, (a, b, c) in enumerate(values):
        y = 220 + i * 30
        lines.append(line(f"{'①②③④'[i]} {a}" if marked else a, 40, y, 90))
        lines.append(line(b, 200, y, 60))
        lines.append(line(c, 340, y, 60))
    return lines


_PERMUTATIONS = [
    ("무결성", "가용성", "기밀성"),
    ("무결성", "기밀성", "가용성"),
    ("기밀성", "가용성", "무결성"),
    ("기밀성", "무결성", "가용성"),
]


def test_choices_without_markers_are_not_a_table():
    """①②③④가 검출되지 않아도, 문제 문장 + 값 반복으로 걸러낸다."""
    lines = _choice_grid(False, _PERMUTATIONS, "다음 중 옳게 짝지은 것은?")
    blocks = layout.analyze_page(lines, 1, 0)
    assert tables(blocks) == [], tables(blocks)


def test_short_table_after_question_stays_a_table():
    """값이 서로 다르면 문제 뒤에 있어도 표다."""
    distinct = [
        ("서울", "부산", "대구"),
        ("인천", "광주", "대전"),
        ("울산", "세종", "제주"),
        ("경기", "강원", "충북"),
    ]
    lines = _choice_grid(False, distinct, "다음 중 옳은 것은?")
    blocks = layout.analyze_page(lines, 1, 0)
    assert tables(blocks) == [(5, 3)], tables(blocks)


def _ruled(*positions: float, x0: float = 35, x1: float = 405) -> RuledLines:
    """가로 괘선만 있는 RuledLines. 4지선다 격자(x 40~400)를 가로지르는 폭이다."""
    return RuledLines(
        horizontal=[Ruling(x0=x0, y0=y - 1, x1=x1, y1=y + 1) for y in positions],
        vertical=[],
    )


def test_ruled_grid_after_question_stays_a_table():
    """괘선이 그어져 있으면 4지선다 판정을 뒤집는다.

    4지선다 판정은 내용 신호(항목 번호, 앞 블록의 물음표, 값 반복)에 기댄다.
    값이 반복되는 진짜 표가 문제 문장 뒤에 오면 잘못 강등되는데,
    그려진 선은 그보다 확실한 증거다.
    """
    lines = _choice_grid(False, _PERMUTATIONS, "다음 중 옳게 짝지은 것은?")
    assert tables(layout.analyze_page(lines, 1, 0)) == [], "괘선 없이는 목록이어야 한다"

    blocks = layout.analyze_page(lines, 1, 0, _ruled(210, 240, 270))
    assert tables(blocks) == [(5, 3)], tables(blocks)


def test_box_border_alone_does_not_make_a_table():
    """네모만 두른 4지선다는 그대로 목록이다.

    상자 테두리는 위아래 2개뿐이라 임계값(3)에 미달한다.
    실제 표는 최소 3개였다(거래명세서 품목표).
    """
    lines = _choice_grid(False, _PERMUTATIONS, "다음 중 옳게 짝지은 것은?")
    blocks = layout.analyze_page(lines, 1, 0, _ruled(170, 340))
    assert tables(blocks) == [], tables(blocks)


def test_narrow_rules_do_not_make_a_table():
    """표 폭을 다 가로지르지 못하는 선은 근거가 안 된다 (본문 밑줄 등)."""
    lines = _choice_grid(False, _PERMUTATIONS, "다음 중 옳게 짝지은 것은?")
    blocks = layout.analyze_page(lines, 1, 0, _ruled(210, 240, 270, x0=120, x1=330))
    assert tables(blocks) == [], tables(blocks)


def test_plain_number_column_stays_a_table():
    """번호만 있는 열('1', '2')은 목록 마커가 아니라 표의 번호 열이다."""
    lines = [
        line("번호", 40, 100, 60),
        line("항목", 200, 100, 60),
        line("금액", 400, 100, 60),
    ]
    for i, (item, amount) in enumerate([("라이선스", "8,400,000"), ("컨설팅", "6,000,000")]):
        y = 140 + i * 40
        lines.append(line(str(i + 1), 40, y, 20))
        lines.append(line(item, 200, y, 120))
        lines.append(line(amount, 400, y, 120))

    blocks = layout.analyze_page(lines, 1, 0)
    assert tables(blocks) == [(3, 3)], tables(blocks)


def test_single_row_is_not_a_table():
    """가로로 늘어선 도표 라벨은 표가 아니다."""
    lines = [
        line("평문", 40, 100, 60),
        line("암호화", 200, 100, 80),
        line("암호문", 400, 100, 80),
        line("복호화", 600, 100, 80),
    ]
    blocks = layout.analyze_page(lines, 1, 0)
    assert tables(blocks) == [], tables(blocks)


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
