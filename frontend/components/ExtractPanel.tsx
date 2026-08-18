"use client";

import { useState } from "react";
import { requestExtract } from "@/lib/api";
import {
  PRESET_OPTIONS,
  type Confidence,
  type ExtractPreset,
  type ExtractResult,
  type OCRResult,
} from "@/lib/types";
import { ms } from "@/lib/format";

const CONFIDENCE_BADGE: Record<Confidence, string> = {
  high: "bg-emerald-500/12 text-emerald-600 dark:text-emerald-400",
  medium: "bg-amber-500/15 text-amber-600 dark:text-amber-400",
  low: "bg-red-500/12 text-red-600 dark:text-red-400",
};

const CONFIDENCE_LABEL: Record<Confidence, string> = {
  high: "명시",
  medium: "추론",
  low: "불확실",
};

interface Props {
  result: OCRResult;
  extractReady: boolean;
  /** 근거 줄을 이미지 위에 짚어준다 */
  onHighlight: (lineIds: number[]) => void;
}

export default function ExtractPanel({ result, extractReady, onHighlight }: Props) {
  const [preset, setPreset] = useState<ExtractPreset>("auto");
  const [data, setData] = useState<ExtractResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await requestExtract(result, preset));
    } catch (e) {
      setError(e instanceof Error ? e.message : "추출에 실패했습니다.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      className="flex flex-col gap-3"
      onMouseLeave={() => onHighlight([])}
    >
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={preset}
          onChange={(e) => setPreset(e.target.value as ExtractPreset)}
          className="rounded-lg border border-border bg-surface px-3 py-1.5 text-sm outline-none"
          aria-label="추출 방식"
        >
          {PRESET_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <button
          onClick={run}
          disabled={loading || !extractReady}
          className="rounded-lg bg-accent px-3 py-1.5 text-sm text-white transition disabled:cursor-not-allowed disabled:opacity-50"
        >
          {loading ? "추출 중…" : data ? "다시 추출" : "항목 추출"}
        </button>
        {data && (
          <span className="text-xs text-muted">
            {data.doc_type} · {ms(data.usage.elapsed_ms)} · $
            {data.usage.cost_usd.toFixed(4)} ·{" "}
            {data.usage.input_tokens + data.usage.output_tokens} 토큰
          </span>
        )}
      </div>

      {!extractReady && (
        <div className="rounded-xl border border-border bg-surface p-4 text-sm text-muted">
          <p className="text-foreground">LLM 항목 추출을 쓰려면 API 키가 필요합니다.</p>
          <pre className="thin-scroll mt-2 overflow-x-auto rounded-lg bg-border/30 p-2 font-mono text-xs">
            export ANTHROPIC_API_KEY=sk-ant-...
          </pre>
          <p className="mt-2">키를 넣고 backend를 다시 실행하면 활성화됩니다.</p>
        </div>
      )}

      {error && (
        <div className="rounded-xl border border-red-500/40 bg-red-500/5 p-3 text-sm text-red-600 dark:text-red-400">
          {error}
        </div>
      )}

      {data?.warnings.map((w) => (
        <div
          key={w}
          className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-2 text-xs text-amber-600 dark:text-amber-400"
        >
          {w}
        </div>
      ))}

      {data && (
        <div className="flex flex-col gap-4">
          <table className="w-full border-collapse text-sm">
            <tbody>
              {data.fields.map((field, i) => (
                <tr
                  key={`${field.key}-${i}`}
                  onMouseEnter={() => onHighlight(field.line_ids)}
                  className="border-b border-border transition hover:bg-accent/5"
                >
                  <td className="w-2/5 py-1.5 pr-3 align-top text-muted">{field.key}</td>
                  <td className="py-1.5 align-top break-words">{field.value}</td>
                  <td className="w-14 py-1.5 pl-2 text-right align-top">
                    <span
                      className={`rounded px-1.5 py-0.5 text-[10px] ${CONFIDENCE_BADGE[field.confidence]}`}
                      title={`근거 줄 ${field.line_ids.join(", ") || "없음"}`}
                    >
                      {CONFIDENCE_LABEL[field.confidence]}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {data.items.length > 0 && (
            <div className="thin-scroll overflow-x-auto">
              <p className="mb-1 text-xs text-muted">품목 {data.items.length}건</p>
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr>
                    {["품목", "수량", "단가", "금액"].map((h) => (
                      <th
                        key={h}
                        className="border border-border bg-border/30 px-2 py-1 text-left font-medium"
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((item, i) => (
                    <tr
                      key={i}
                      onMouseEnter={() => onHighlight(item.line_ids)}
                      className="transition hover:bg-accent/5"
                    >
                      <td className="border border-border px-2 py-1">{item.name}</td>
                      <td className="border border-border px-2 py-1">{item.quantity}</td>
                      <td className="border border-border px-2 py-1">{item.unit_price}</td>
                      <td className="border border-border px-2 py-1">{item.amount}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <p className="text-xs text-muted">
            행에 마우스를 올리면 이미지에서 근거가 된 줄을 짚어줍니다. · {data.usage.model}
          </p>
        </div>
      )}
    </div>
  );
}
