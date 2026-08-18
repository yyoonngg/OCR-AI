"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import ExtractPanel from "./ExtractPanel";
import type { LayoutBlock, OCRResult, QualityLevel } from "@/lib/types";
import { TIER_BADGE, TIER_LABEL, ms, pct, tierOf } from "@/lib/format";

type Tab = "lines" | "layout" | "extract" | "text" | "json";

interface Props {
  result: OCRResult;
  /** 줄 목록은 이미지에 보이는 쪽만 보여줘야 오버레이와 호버가 어긋나지 않는다. */
  page: number;
  activeId: number | null;
  activeBlockId: number | null;
  extractReady: boolean;
  onHover: (id: number | null) => void;
  onHoverBlock: (id: number | null) => void;
  onHighlight: (lineIds: number[]) => void;
}

export default function ResultPanel({
  result,
  page,
  activeId,
  activeBlockId,
  extractReady,
  onHover,
  onHoverBlock,
  onHighlight,
}: Props) {
  const [tab, setTab] = useState<Tab>("lines");
  const [copied, setCopied] = useState(false);
  const listRef = useRef<HTMLUListElement>(null);

  const multiPage = result.pages.length > 1;
  const visibleLines = useMemo(
    () => (multiPage ? result.lines.filter((l) => l.page === page) : result.lines),
    [result.lines, multiPage, page],
  );
  const visibleBlocks = useMemo(
    () => (multiPage ? result.blocks.filter((b) => b.page === page) : result.blocks),
    [result.blocks, multiPage, page],
  );

  const stats = useMemo(() => {
    const n = result.lines.length;
    const avg = n ? result.lines.reduce((s, l) => s + l.confidence, 0) / n : 0;
    // 백엔드가 센 값을 그대로 쓴다. 경계를 양쪽에서 따로 두면 화면과 경고문이 어긋난다.
    const lowCount = result.quality.low_confidence_lines;
    const chars = result.lines.reduce((s, l) => s + l.text.length, 0);
    return { n, avg, lowCount, chars };
  }, [result.lines, result.quality.low_confidence_lines]);

  // 이미지에서 박스를 고르면 해당 줄이 목록에 보이도록 스크롤한다.
  useEffect(() => {
    if (activeId === null || tab !== "lines") return;
    listRef.current
      ?.querySelector(`[data-line="${activeId}"]`)
      ?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [activeId, tab]);

  const copy = async () => {
    await navigator.clipboard.writeText(tab === "layout" ? result.markdown : result.full_text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const download = (kind: "txt" | "md" | "json") => {
    const body =
      kind === "txt"
        ? result.full_text
        : kind === "md"
          ? result.markdown
          : JSON.stringify(stripImages(result), null, 2);
    const type =
      kind === "json" ? "application/json" : `text/${kind === "md" ? "markdown" : "plain"};charset=utf-8`;
    const url = URL.createObjectURL(new Blob([body], { type }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `${result.filename.replace(/\.[^.]+$/, "")}.${kind}`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const textLayerPages = result.pages.filter((p) => p.source === "pdf_text").length;

  return (
    <div className="flex h-full flex-col gap-4">
      {textLayerPages > 0 && (
        <div className="rounded-xl border border-emerald-500/40 bg-emerald-500/5 p-3 text-sm text-emerald-600 dark:text-emerald-400">
          <p className="font-medium">
            PDF 텍스트 레이어에서 읽었습니다 — OCR을 건너뛰었습니다
            {result.pages.length > textLayerPages &&
              ` (${result.pages.length}쪽 중 ${textLayerPages}쪽)`}
          </p>
          <p className="mt-1 text-xs opacity-90">
            원본 글자를 그대로 가져온 것이라 인식 오류가 없습니다. 우상단 &quot;강제 OCR&quot;로
            같은 파일을 OCR 경로와 비교할 수 있습니다.
          </p>
        </div>
      )}

      {result.quality.level !== "good" && (
        <div className={`rounded-xl border p-3 text-sm ${QUALITY_STYLE[result.quality.level]}`}>
          <p className="font-medium">
            {result.quality.level === "poor"
              ? "입력 품질이 낮습니다 — 결과를 그대로 신뢰하지 마세요"
              : "입력 품질에 여유가 없습니다"}
          </p>
          <ul className="mt-1 flex list-disc flex-col gap-0.5 pl-4 text-xs opacity-90">
            {result.quality.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="grid grid-cols-3 gap-2 lg:grid-cols-6">
        <Stat label="인식 줄" value={`${stats.n}`} />
        <Stat label="글자 수" value={`${stats.chars}`} />
        <Stat
          label="평균 신뢰도"
          value={pct(stats.avg)}
          tone={stats.avg >= 0.9 ? "good" : "warn"}
        />
        {/* "확인 필요"는 나머지가 맞다는 뜻으로 읽힌다. 실측 재현율이 53%라 그렇게 못 쓴다. */}
        <Stat
          label="신뢰도 낮음"
          value={`${stats.lowCount}줄`}
          tone={stats.lowCount ? "warn" : undefined}
        />
        <Stat
          label="띄어쓰기 복원"
          value={`${result.spacing_fixed_lines}줄`}
          tone={result.spacing_fixed_lines ? "accent" : undefined}
        />
        <Stat
          label={result.page_columns > 1 ? `표 · ${result.page_columns}단` : "표"}
          value={`${result.table_count}개`}
          tone={result.table_count ? "accent" : undefined}
        />
      </div>

      <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted">
        <Chip>검출 {ms(result.timing.detect_ms)}</Chip>
        <Chip>방향보정 {ms(result.timing.classify_ms)}</Chip>
        <Chip>인식 {ms(result.timing.recognize_ms)}</Chip>
        <Chip>띄어쓰기 {ms(result.timing.spacing_ms)}</Chip>
        <Chip>괘선 {ms(result.timing.rules_ms)}</Chip>
        <Chip>레이아웃 {ms(result.timing.layout_ms)}</Chip>
        <Chip strong>합계 {ms(result.timing.total_ms)}</Chip>
      </div>

      <div className="flex items-center justify-between gap-2 border-b border-border">
        <div className="flex">
          {(
            [
              ["lines", "줄 단위"],
              ["layout", "레이아웃"],
              ["extract", "항목 추출"],
              ["text", "전체 텍스트"],
              ["json", "JSON"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={`-mb-px border-b-2 px-3 py-2 text-sm transition ${
                tab === key
                  ? "border-accent text-foreground"
                  : "border-transparent text-muted hover:text-foreground"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1 pb-1">
          <SmallButton onClick={copy}>{copied ? "복사됨" : "복사"}</SmallButton>
          <SmallButton onClick={() => download("txt")}>.txt</SmallButton>
          <SmallButton onClick={() => download("md")}>.md</SmallButton>
          <SmallButton onClick={() => download("json")}>.json</SmallButton>
        </div>
      </div>

      <div className="thin-scroll min-h-0 flex-1 overflow-auto">
        {tab === "lines" && (
          <ul ref={listRef} className="flex flex-col gap-1.5">
            {visibleLines.map((line) => {
              const tier = tierOf(line.confidence);
              return (
                <li
                  key={line.id}
                  data-line={line.id}
                  onMouseEnter={() => onHover(line.id)}
                  onMouseLeave={() => onHover(null)}
                  className={`flex items-start gap-3 rounded-lg border px-3 py-2 transition ${
                    activeId === line.id
                      ? "border-accent bg-accent/5"
                      : "border-border bg-surface"
                  }`}
                >
                  <span className="mt-0.5 w-8 shrink-0 text-right font-mono text-xs text-muted">
                    {line.id + 1}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="break-words text-sm leading-relaxed">{line.text}</p>
                    {line.spacing_fixed && (
                      <p className="mt-1 flex items-baseline gap-1.5 break-words text-xs text-muted">
                        <span className="shrink-0 rounded bg-accent/12 px-1 py-0.5 text-[10px] text-accent">
                          띄어쓰기 복원
                        </span>
                        <span className="font-mono">{line.raw_text}</span>
                      </p>
                    )}
                  </div>
                  <span
                    className={`shrink-0 rounded-md px-1.5 py-0.5 font-mono text-[11px] ${TIER_BADGE[tier]}`}
                    title={`신뢰도 ${TIER_LABEL[tier]}`}
                  >
                    {pct(line.confidence)}
                  </span>
                </li>
              );
            })}
          </ul>
        )}

        {tab === "layout" && (
          <div className="flex flex-col gap-3">
            {visibleBlocks.length === 0 && (
              <p className="text-sm text-muted">레이아웃 분석이 꺼져 있습니다.</p>
            )}
            {visibleBlocks.map((block, index) => (
              <BlockView
                key={block.id}
                block={block}
                index={index}
                showColumn={result.page_columns > 1}
                active={block.id === activeBlockId}
                onHover={onHoverBlock}
              />
            ))}
          </div>
        )}

        {tab === "extract" && (
          <ExtractPanel
            result={result}
            extractReady={extractReady}
            onHighlight={onHighlight}
          />
        )}

        {tab === "text" && (
          <textarea
            readOnly
            value={result.full_text}
            className="h-full min-h-80 w-full resize-none rounded-lg border border-border bg-surface p-3 font-mono text-sm leading-relaxed outline-none"
          />
        )}

        {tab === "json" && (
          <pre className="thin-scroll overflow-auto rounded-lg border border-border bg-surface p-3 font-mono text-xs leading-relaxed">
            {JSON.stringify(stripImages(result), null, 2)}
          </pre>
        )}
      </div>
    </div>
  );
}

const QUALITY_STYLE: Record<QualityLevel, string> = {
  good: "",
  fair: "border-amber-500/40 bg-amber-500/5 text-amber-600 dark:text-amber-400",
  poor: "border-red-500/40 bg-red-500/5 text-red-600 dark:text-red-400",
};

function BlockView({
  block,
  index,
  showColumn,
  active,
  onHover,
}: {
  block: LayoutBlock;
  index: number;
  showColumn: boolean;
  active: boolean;
  onHover: (id: number | null) => void;
}) {
  const grid = useMemo(() => {
    const rows: string[][] = Array.from({ length: block.rows }, () =>
      Array.from({ length: block.columns }, () => ""),
    );
    for (const cell of block.cells) rows[cell.row][cell.column] = cell.text;
    return rows;
  }, [block]);

  const header = block.has_header ? grid[0] : null;
  const body = block.has_header ? grid.slice(1) : grid;

  return (
    <section
      onMouseEnter={() => onHover(block.id)}
      onMouseLeave={() => onHover(null)}
      className={`rounded-xl border p-3 transition ${
        active ? "border-accent bg-accent/5" : "border-border bg-surface"
      }`}
    >
      <p className="mb-2 flex items-center gap-2 text-xs text-muted">
        <span className="flex h-5 w-5 items-center justify-center rounded-full bg-accent/15 font-mono text-[11px] text-accent">
          {index + 1}
        </span>
        {block.kind === "table" ? `표 ${block.rows}×${block.columns}` : "본문"}
        {showColumn && <span>· {block.page_column + 1}단</span>}
      </p>

      {block.kind === "text" ? (
        <p className="whitespace-pre-line break-words text-sm leading-relaxed">
          {block.text}
        </p>
      ) : (
        <div className="thin-scroll overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            {header && (
              <thead>
                <tr>
                  {header.map((cell, i) => (
                    <th
                      key={i}
                      className="border border-border bg-border/30 px-2 py-1 text-left font-medium"
                    >
                      {cell}
                    </th>
                  ))}
                </tr>
              </thead>
            )}
            <tbody>
              {body.map((row, r) => (
                <tr key={r}>
                  {row.map((cell, c) => (
                    <td key={c} className="border border-border px-2 py-1 align-top">
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/** base64 이미지는 JSON으로 볼 때 방해만 되므로 뺀다. */
function stripImages(result: OCRResult) {
  return {
    ...result,
    pages: result.pages.map((p) => ({
      page: p.page,
      width: p.width,
      height: p.height,
    })),
  };
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "good" | "warn" | "accent";
}) {
  const toneClass =
    tone === "warn"
      ? "text-amber-600 dark:text-amber-400"
      : tone === "good"
        ? "text-emerald-600 dark:text-emerald-400"
        : tone === "accent"
          ? "text-accent"
          : "";
  return (
    <div className="rounded-xl border border-border bg-surface px-3 py-2">
      <p className="truncate text-xs text-muted">{label}</p>
      <p className={`mt-0.5 font-mono text-lg ${toneClass}`}>{value}</p>
    </div>
  );
}

function Chip({ children, strong }: { children: React.ReactNode; strong?: boolean }) {
  return (
    <span
      className={`rounded-md border border-border px-2 py-1 font-mono ${
        strong ? "text-foreground" : ""
      }`}
    >
      {children}
    </span>
  );
}

function SmallButton({
  children,
  onClick,
}: {
  children: React.ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="rounded-md border border-border px-2 py-1 text-xs text-muted transition hover:text-foreground"
    >
      {children}
    </button>
  );
}
