"""PDF 텍스트 레이어 줄 재구성 테스트.

임계값은 실제 문서의 문자 간격 분포에서 뽑았다(app/pdftext.py 상단 주석).
여기 있는 케이스는 전부 실제로 한 번씩 깨졌던 것들이다.
문서: docs/troubleshooting/12-PDF-텍스트-레이어에서-줄이-쪼개진다.md

    실행: ./.venv/bin/python tests/test_pdftext.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pdftext import _Char, _merge_fragments, _render_text, _split_fragments  # noqa: E402


def ch(text: str, left: float, top: float, width: float = 12, height: float = 14) -> _Char:
    """실제 파이프라인은 loose 박스(폰트 라인박스)를 쓴다.

    그래서 같은 줄의 글자는 폭이 달라도 세로 범위가 같다. 쉼표처럼 좁은 글자도 마찬가지다.
    테스트 데이터도 그 성질을 지켜야 실제와 같은 경로를 탄다.
    """
    return _Char(text=text, left=left, top=top, right=left + width, bottom=top + height)


def build(chars: list[_Char]) -> list[str]:
    lines = []
    for group in _merge_fragments(_split_fragments(chars)):
        group.sort(key=lambda c: c.left)
        lines.append(_render_text(group))
    return lines


def test_comma_stays_on_the_line():
    """폭이 좁은 쉼표도 같은 줄로 남아야 한다.

    잉크 범위(tight) 박스를 쓰면 `스`의 bottom과 뒤따르는 `,`의 top이 정확히 같아져
    세로 겹침이 0이 되고, 문장 한가운데서 줄이 끊긴다. loose 박스가 이걸 막는다.
    """
    chars = [
        ch("사", 100, 318),
        ch("람", 113, 318),
        ch(",", 126, 318, width=4),  # 폭만 좁고 세로 범위는 같다
        ch("인", 138, 318),
        ch("가", 151, 318),
    ]
    assert build(chars) == ["사람, 인가"], build(chars)


def test_tight_box_would_break_the_line():
    """왜 loose 박스를 쓰는지 — tight 박스면 쉼표에서 줄이 끊긴다는 근거."""
    chars = [
        ch("사", 100, 318),
        ch("람", 113, 318),
        _Char(text=",", left=126, top=332, right=130, bottom=335),  # 겹침 0
        ch("인", 138, 318),
    ]
    assert build(chars) != ["사람, 인"], "tight 박스에서도 붙는다면 loose를 쓸 이유가 없다"


def test_table_cells_are_separated():
    """가로로 크게 벌어지면 다른 셀이다."""
    chars = [ch("구", 100, 300), ch("분", 113, 300), ch("개", 400, 300), ch("념", 413, 300)]
    assert build(chars) == ["구분", "개념"], build(chars)


def test_tight_letters_get_no_space():
    """붙어 있는 글자는 간격 최대 0.30(높이 대비). 공백을 넣으면 안 된다."""
    chars = [ch("보", 100, 300), ch("안", 112 + 4.2, 300)]  # 간격 4.2 = 높이 14 * 0.30
    assert build(chars) == ["보안"], build(chars)


def test_word_space_is_restored():
    """공백 하나는 간격 중앙값 0.53(높이 대비)."""
    chars = [ch("보", 100, 300), ch("안", 112 + 7.4, 300)]  # 간격 7.4 = 높이 14 * 0.53
    assert build(chars) == ["보 안"], build(chars)


def test_different_rows_stay_separate():
    chars = [ch("첫", 100, 300), ch("줄", 113, 300), ch("둘", 100, 340), ch("째", 113, 340)]
    assert build(chars) == ["첫줄", "둘째"], build(chars)


def test_out_of_order_fragments_are_merged_by_geometry():
    """PDF 문자 순서는 시각적 순서와 다를 수 있다 (텍스트 오브젝트 경계에서 점프).

    실제 PDF에서 이 병합이 303조각 → 170줄까지 붙인 적이 있다. 죽은 코드가 아니다.
    """
    chars = [ch("뒤", 118, 300), ch("앞", 100, 300)]  # 순서가 뒤집혀 들어옴
    assert build(chars) == ["앞 뒤"], build(chars)


def test_vertically_offset_fragments_are_merged():
    """세로로 조금 어긋난 조각도 같은 줄이다 (겹침이 충분하면)."""
    chars = [ch("뒤", 118, 304), ch("앞", 100, 300)]  # 4px 어긋남 + 순서 뒤집힘
    assert build(chars) == ["앞 뒤"], build(chars)


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
