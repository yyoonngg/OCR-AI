"""입력 품질 판정 테스트.

임계값은 저품질 입력 벤치마크의 실측(신뢰도 ↔ 줄 CER)에서 뽑았다.
문서: docs/troubleshooting/10-저품질-입력은-전처리로-못-고친다.md

    실행: ./.venv/bin/python tests/test_quality.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.quality import assess  # noqa: E402
from app.schemas import BBox, TextLine  # noqa: E402


def line(confidence: float, height: float = 30) -> TextLine:
    return TextLine(
        id=0,
        text="가나다라",
        raw_text="가나다라",
        spacing_fixed=False,
        confidence=confidence,
        polygon=[(0, 0), (100, 0), (100, height), (0, height)],
        bbox=BBox(x=0, y=0, width=100, height=height),
    )


def test_clean_scan_is_good():
    """실측 0.949 / 25px → 줄 CER 0%."""
    report = assess([line(0.95) for _ in range(20)])
    assert report.level == "good", report
    assert report.notes == []


def test_blurred_page_is_poor():
    """실측 0.801 → 줄 CER 31.6%. 반드시 경고해야 한다."""
    report = assess([line(0.80) for _ in range(20)])
    assert report.level == "poor", report
    assert any("신뢰도" in n for n in report.notes)


def test_downscaled_page_is_poor_on_height():
    """신뢰도가 애매해도 글자가 13px면 위험하다 (실측 CER 22.7%)."""
    report = assess([line(0.92, height=13) for _ in range(20)])
    assert report.level == "poor", report
    assert any("글자 높이" in n for n in report.notes)


def test_borderline_is_fair():
    """0.87~0.94 구간은 줄 CER 3~13%. 쓸 수는 있지만 확인이 필요하다."""
    report = assess([line(0.91) for _ in range(20)])
    assert report.level == "fair", report


def test_low_confidence_lines_are_counted():
    lines = [line(0.98) for _ in range(18)] + [line(0.4), line(0.5)]
    report = assess(lines)
    assert report.low_confidence_lines == 2, report


def test_realistic_misreads_are_flagged():
    """예전 임계값 0.75는 실전에서 아무것도 못 잡았다.

    정답을 놓고 682줄을 재 보니 0.75 미만인 줄이 0개였다. 오독은 109줄이었는데도.
    실제 오독의 신뢰도는 0.88~0.93 근처에 몰려 있다 (14번 문서).
    """
    misread = [line(0.88), line(0.90), line(0.93)]
    report = assess([line(0.98) for _ in range(17)] + misread)

    # 0.91 미만인 두 줄이 잡혀야 한다. 0.75 기준이었으면 0줄이다.
    assert report.low_confidence_lines == 2, report
    assert any("이것만 믿지는" in note for note in report.notes), report.notes


def test_empty_input():
    report = assess([])
    assert report.level == "poor"
    assert report.notes


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
