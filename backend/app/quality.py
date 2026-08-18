"""입력 품질 판정 — 결과를 믿어도 되는지 미리 알려준다.

저품질 입력 벤치마크에서 나온 결론 두 가지가 이 모듈의 근거다.

1. **전처리로는 못 고친다.** 업스케일·언샤프 마스크를 붙여 봤지만 개선이 없거나
   오히려 나빠졌다 (흐린 교재 페이지: CER 31.6% → 확대 40.3% → 확대+선명 46.0%).
   해상도나 초점에서 이미 사라진 정보는 리샘플링으로 돌아오지 않는다.

2. **대신 평균 신뢰도가 심한 열화는 잡아낸다.** 아래는 실측이다.

   | 평균 신뢰도 | 줄 CER |
   | --- | --- |
   | 0.949 (원본)      | 0.0%  |
   | 0.945 (흐림 r=1)  | 2.3%  |
   | 0.925 (축소 60%)  | 6.1%  |
   | 0.895 (팩스본)     | 12.6% |
   | 0.878 (휴대폰 사진) | 15.3% |
   | 0.824 (축소 40%)  | 22.7% |
   | 0.801 (흐림 r=2)  | 31.6% |

   그래서 고치는 대신 **미리 경고한다.** 사람이 결과를 그대로 믿을지, 원본을 다시
   받을지 판단할 근거를 준다.

## 여기까지가 페이지 단위 이야기다. 줄 단위로는 훨씬 약하다

나중에 PDF 텍스트 레이어를 진짜 정답으로 놓고 줄 단위로 다시 쟀더니
(682줄, docs/troubleshooting/14번) 위 표만큼 깨끗하지 않았다.

- **중간 정도 열화는 구별하지 못한다.** 위 표의 조건들은 신뢰도가 0.80대까지 떨어지는
  극단이다. 그림자·JPEG·노이즈처럼 신뢰도가 0.94 근처에 머무는 조건에서는
  오독이 12줄에서 24줄로 두 배가 되는 동안 평균 신뢰도가 오히려 올라가기도 했다
- **줄 하나가 틀렸는지는 거의 못 맞힌다.** 임계값을 어디에 두든 F1이 0.43을 못 넘는다.
  글자별 신뢰도의 최솟값을 써 봐도 더 나빴다(0.35). 엔진이 주는 신호에 답이 없다

그래서 `low_confidence_lines`는 "이것만 보면 된다"가 아니라 "여기부터 보라"는 힌트다.
"""

from __future__ import annotations

from .schemas import QualityLevel, QualityReport, TextLine

# 위 표에서 뽑은 경계. 0.94 위는 거의 무오류, 0.87 아래는 두 자릿수 CER.
GOOD_CONFIDENCE = 0.94
FAIR_CONFIDENCE = 0.87

# 글자가 이보다 작아지면 인식률이 급격히 떨어진다.
# 실측: 25px → CER 0%, 13px → CER 22.7%. 13px가 poor에 들어가도록 경계를 14로 둔다.
GOOD_HEIGHT = 20.0
FAIR_HEIGHT = 14.0

# 직접 확인해 보라고 짚어 줄 줄의 신뢰도 경계.
#
# 원래 0.75였는데, 정답을 놓고 재 보니 **682줄 중 0줄**을 잡았다. 오독이 109줄(16%)
# 있는데 재현율 0%였다. 열화를 걸어도 줄 신뢰도가 0.75 아래로는 잘 내려가지 않는다.
# "확인 필요 0줄"이 언제나 0줄이었던 것이다.
#
# 아래는 같은 표본에서 임계값별 성능이다 (오독 109줄을 잡는 기준).
#
#   0.94   303줄 표시   정밀도 24%   재현율 67%   F1 0.35
#   0.91   167줄 표시   정밀도 35%   재현율 53%   F1 0.42  ← 채택
#   0.87    32줄 표시   정밀도 66%   재현율 19%   F1 0.30
#   0.75     0줄 표시   정밀도  0%   재현율  0%
#
# F1이 가장 높은 지점을 골랐다. 그래도 정밀도 35%다 — 짚어 준 줄의 3분의 2는 멀쩡하고,
# 오독의 절반은 못 잡는다. 이 지표의 한계를 알고 써야 한다 (14번 문서).
LOW_LINE_CONFIDENCE = 0.91


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[len(ordered) // 2] if ordered else 0.0


def assess(lines: list[TextLine]) -> QualityReport:
    if not lines:
        return QualityReport(
            level="poor",
            avg_confidence=0.0,
            median_line_height=0.0,
            low_confidence_lines=0,
            notes=["텍스트를 찾지 못했습니다. 해상도가 너무 낮거나 글자가 없는 이미지입니다."],
        )

    avg = sum(line.confidence for line in lines) / len(lines)
    height = _median([line.bbox.height for line in lines])
    low = sum(1 for line in lines if line.confidence < LOW_LINE_CONFIDENCE)

    notes: list[str] = []
    level: QualityLevel = "good"

    if avg < FAIR_CONFIDENCE:
        level = "poor"
        notes.append(
            f"평균 신뢰도 {avg:.2f} — 이 구간에서는 글자 오류율이 10%를 넘습니다. "
            "결과를 그대로 쓰지 말고 원본을 다시 확보하세요."
        )
    elif avg < GOOD_CONFIDENCE:
        level = "fair"
        notes.append(f"평균 신뢰도 {avg:.2f} — 군데군데 오인식이 섞여 있을 수 있습니다.")

    if height < FAIR_HEIGHT:
        level = "poor"
        notes.append(
            f"글자 높이 중앙값 {height:.0f}px — 너무 작습니다. "
            "스캔 해상도를 300dpi 이상으로 올리는 게 확대보다 확실합니다."
        )
    elif height < GOOD_HEIGHT and level == "good":
        level = "fair"
        notes.append(f"글자 높이 중앙값 {height:.0f}px — 여유가 크지 않습니다.")

    if low:
        # "이것만 보면 된다"로 읽히지 않게 쓴다. 실측 재현율이 53%라 절반은 못 잡는다.
        notes.append(
            f"신뢰도 {LOW_LINE_CONFIDENCE} 미만인 줄이 {low}개 있습니다. 먼저 확인해 보세요 — "
            "다만 오인식의 약 절반은 이 목록에 안 잡히니 이것만 믿지는 마세요."
        )

    return QualityReport(
        level=level,
        avg_confidence=round(avg, 4),
        median_line_height=round(height, 1),
        low_confidence_lines=low,
        notes=notes,
    )
