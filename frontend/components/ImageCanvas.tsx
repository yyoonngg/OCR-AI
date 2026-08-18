"use client";

import { useState } from "react";
import Image from "next/image";
import type { OCRResult } from "@/lib/types";
import { TIER_STROKE, tierOf } from "@/lib/format";

type Overlay = "lines" | "blocks" | "off";

interface Props {
  result: OCRResult;
  page: number;
  onPageChange: (page: number) => void;
  activeId: number | null;
  activeBlockId: number | null;
  /** 추출된 항목의 근거 줄. 오버레이 모드와 무관하게 항상 표시한다 */
  highlightIds: number[];
  onHover: (id: number | null) => void;
  onSelect: (id: number) => void;
  onHoverBlock: (id: number | null) => void;
}

export default function ImageCanvas({
  result,
  page,
  onPageChange,
  activeId,
  activeBlockId,
  highlightIds,
  onHover,
  onSelect,
  onHoverBlock,
}: Props) {
  const [overlay, setOverlay] = useState<Overlay>("lines");
  const pageInfo = result.pages.find((p) => p.page === page) ?? result.pages[0];
  const lines = result.lines.filter((l) => l.page === pageInfo.page);
  const blocks = result.blocks.filter((b) => b.page === pageInfo.page);
  const highlighted = lines.filter((l) => highlightIds.includes(l.id));

  // 이미지 크기가 제각각이라 라벨 크기를 픽셀 좌표에 맞춰 잡는다.
  const labelSize = Math.max(pageInfo.width / 55, 14);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-1">
          {result.pages.length > 1 &&
            result.pages.map((p) => (
              <button
                key={p.page}
                onClick={() => onPageChange(p.page)}
                className={`rounded-lg px-3 py-1 text-sm transition ${
                  p.page === pageInfo.page
                    ? "bg-accent text-white"
                    : "bg-surface text-muted hover:text-foreground"
                }`}
              >
                {p.page}쪽
              </button>
            ))}
        </div>
        <div className="flex items-center gap-0.5 rounded-lg border border-border bg-surface p-0.5 text-xs">
          {(
            [
              ["lines", `줄 ${lines.length}`],
              ["blocks", `블록 ${blocks.length}`],
              ["off", "끄기"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              onClick={() => setOverlay(key)}
              className={`rounded-md px-2.5 py-1 transition ${
                overlay === key ? "bg-accent text-white" : "text-muted hover:text-foreground"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="relative overflow-hidden rounded-xl border border-border bg-surface">
        <Image
          src={pageInfo.image_data_url}
          alt={`${result.filename} ${pageInfo.page}쪽`}
          width={pageInfo.width}
          height={pageInfo.height}
          unoptimized
          className="block h-auto w-full"
        />

        {overlay === "lines" && (
          <svg
            viewBox={`0 0 ${pageInfo.width} ${pageInfo.height}`}
            className="absolute inset-0 h-full w-full"
            onMouseLeave={() => onHover(null)}
          >
            {lines.map((line) => {
              const active = line.id === activeId;
              const stroke = TIER_STROKE[tierOf(line.confidence)];
              return (
                <polygon
                  key={line.id}
                  points={line.polygon.map(([x, y]) => `${x},${y}`).join(" ")}
                  fill={active ? stroke : "transparent"}
                  fillOpacity={active ? 0.18 : 0}
                  stroke={stroke}
                  strokeWidth={active ? 3 : 1.5}
                  vectorEffect="non-scaling-stroke"
                  className="cursor-pointer transition-[stroke-width]"
                  onMouseEnter={() => onHover(line.id)}
                  onClick={() => onSelect(line.id)}
                >
                  <title>
                    {line.text} ({(line.confidence * 100).toFixed(1)}%)
                  </title>
                </polygon>
              );
            })}
          </svg>
        )}

        {overlay === "blocks" && (
          <svg
            viewBox={`0 0 ${pageInfo.width} ${pageInfo.height}`}
            className="absolute inset-0 h-full w-full"
            onMouseLeave={() => onHoverBlock(null)}
          >
            {blocks.map((block, index) => {
              const active = block.id === activeBlockId;
              const color = block.kind === "table" ? "#6366f1" : "#64748b";
              const pad = labelSize * 0.3;
              return (
                <g
                  key={block.id}
                  className="cursor-pointer"
                  onMouseEnter={() => onHoverBlock(block.id)}
                >
                  <rect
                    x={block.bbox.x - pad}
                    y={block.bbox.y - pad}
                    width={block.bbox.width + pad * 2}
                    height={block.bbox.height + pad * 2}
                    rx={pad}
                    fill={color}
                    fillOpacity={active ? 0.16 : 0.05}
                    stroke={color}
                    strokeWidth={active ? 3 : 1.5}
                    vectorEffect="non-scaling-stroke"
                  />
                  {/* 표는 셀 경계까지 그려서 행·열이 맞게 잡혔는지 바로 보이게 한다 */}
                  {block.kind === "table" &&
                    block.cells.map((cell) => (
                      <rect
                        key={`${cell.row}-${cell.column}`}
                        x={cell.bbox.x}
                        y={cell.bbox.y}
                        width={cell.bbox.width}
                        height={cell.bbox.height}
                        fill="none"
                        stroke={color}
                        strokeWidth={1}
                        strokeDasharray="4 3"
                        vectorEffect="non-scaling-stroke"
                      />
                    ))}
                  <circle
                    cx={block.bbox.x - pad}
                    cy={block.bbox.y - pad}
                    r={labelSize * 0.62}
                    fill={color}
                  />
                  <text
                    x={block.bbox.x - pad}
                    y={block.bbox.y - pad}
                    fill="#fff"
                    fontSize={labelSize * 0.75}
                    textAnchor="middle"
                    dominantBaseline="central"
                  >
                    {index + 1}
                  </text>
                  <title>
                    {block.kind === "table"
                      ? `표 ${block.rows}×${block.columns}`
                      : "본문"}{" "}
                    · 단 {block.page_column + 1}
                  </title>
                </g>
              );
            })}
          </svg>
        )}

        {/* 추출 항목의 근거 줄 — 오버레이 모드와 무관하게 항상 위에 그린다 */}
        {highlighted.length > 0 && (
          <svg
            viewBox={`0 0 ${pageInfo.width} ${pageInfo.height}`}
            className="pointer-events-none absolute inset-0 h-full w-full"
          >
            {highlighted.map((line) => (
              <polygon
                key={line.id}
                points={line.polygon.map(([x, y]) => `${x},${y}`).join(" ")}
                fill="var(--accent)"
                fillOpacity={0.22}
                stroke="var(--accent)"
                strokeWidth={3}
                vectorEffect="non-scaling-stroke"
              />
            ))}
          </svg>
        )}
      </div>
    </div>
  );
}
