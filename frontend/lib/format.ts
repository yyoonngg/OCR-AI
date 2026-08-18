/**
 * 신뢰도 구간. 경계는 백엔드 `app/quality.py`와 같은 값을 쓴다.
 *
 * 정답을 놓고 재 보면 이 신뢰도는 오인식을 절반쯤만 잡아낸다
 * (0.91 기준 정밀도 35% / 재현율 53%). 색은 "여기부터 보라"는 힌트이지
 * "나머지는 맞다"는 보증이 아니다. docs/troubleshooting/14번 참고.
 */
export type ConfidenceTier = "high" | "mid" | "low";

export function tierOf(confidence: number): ConfidenceTier {
  if (confidence >= 0.91) return "high";
  if (confidence >= 0.87) return "mid";
  return "low";
}

export const TIER_STROKE: Record<ConfidenceTier, string> = {
  high: "#22c55e",
  mid: "#f59e0b",
  low: "#ef4444",
};

export const TIER_BADGE: Record<ConfidenceTier, string> = {
  high: "bg-emerald-500/12 text-emerald-600 dark:text-emerald-400",
  mid: "bg-amber-500/15 text-amber-600 dark:text-amber-400",
  low: "bg-red-500/12 text-red-600 dark:text-red-400",
};

export const TIER_LABEL: Record<ConfidenceTier, string> = {
  high: "높음",
  mid: "보통",
  low: "낮음",
};

export function pct(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

export function ms(value: number): string {
  return value >= 1000 ? `${(value / 1000).toFixed(2)}s` : `${Math.round(value)}ms`;
}
