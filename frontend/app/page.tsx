"use client";

import { useCallback, useEffect, useState } from "react";
import Dropzone from "@/components/Dropzone";
import ImageCanvas from "@/components/ImageCanvas";
import ResultPanel from "@/components/ResultPanel";
import { checkHealth, requestOCR } from "@/lib/api";
import { LANG_OPTIONS, type LangCode, type OCRResult } from "@/lib/types";

export default function Home() {
  const [lang, setLang] = useState<LangCode>("korean");
  const [useAngleCls, setUseAngleCls] = useState(false);
  const [restoreSpacing, setRestoreSpacing] = useState(true);
  const [analyzeLayout, setAnalyzeLayout] = useState(true);
  const [forceOcr, setForceOcr] = useState(false);
  const [result, setResult] = useState<OCRResult | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [activeBlockId, setActiveBlockId] = useState<number | null>(null);
  const [online, setOnline] = useState<boolean | null>(null);
  const [extractReady, setExtractReady] = useState(false);
  const [highlightIds, setHighlightIds] = useState<number[]>([]);

  useEffect(() => {
    checkHealth().then((h) => {
      setOnline(h.online);
      setExtractReady(h.extractReady);
    });
  }, []);

  const process = useCallback(
    async (file: File | Blob, name = "upload") => {
      setLoading(true);
      setError(null);
      setResult(null);
      setActiveId(null);
      setActiveBlockId(null);
      setHighlightIds([]);
      setPage(1);

      const objectUrl = URL.createObjectURL(file);
      setPreview(file.type === "application/pdf" ? null : objectUrl);

      try {
        setResult(
          await requestOCR(
            file,
            { lang, useAngleCls, restoreSpacing, analyzeLayout, forceOcr },
            name,
          ),
        );
        setOnline(true);
      } catch (e) {
        setError(
          e instanceof Error && e.message !== "Failed to fetch"
            ? e.message
            : "백엔드에 연결하지 못했습니다. backend 서버가 8000 포트에서 실행 중인지 확인하세요.",
        );
      } finally {
        setLoading(false);
        URL.revokeObjectURL(objectUrl);
      }
    },
    [lang, useAngleCls, restoreSpacing, analyzeLayout, forceOcr],
  );

  const runSample = useCallback(async () => {
    const res = await fetch("/sample.png");
    await process(await res.blob(), "sample.png");
  }, [process]);

  return (
    <main className="mx-auto flex w-full max-w-[1400px] flex-1 flex-col gap-6 p-5 sm:p-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">OCR Playground</h1>
          <p className="mt-1 text-sm text-muted">
            한글 문서·스캔본을 넣으면 줄 단위 텍스트와 위치·신뢰도를 그대로 보여줍니다.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <select
            value={lang}
            onChange={(e) => setLang(e.target.value as LangCode)}
            className="rounded-lg border border-border bg-surface px-3 py-2 text-sm outline-none"
            aria-label="인식 언어"
          >
            {LANG_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <label
            className="flex cursor-pointer items-center gap-2 text-sm text-muted"
            title="인식 모델이 흘린 공백을 원본 이미지의 실제 여백 기준으로 되살립니다."
          >
            <input
              type="checkbox"
              checked={restoreSpacing}
              onChange={(e) => setRestoreSpacing(e.target.checked)}
              className="accent-[var(--accent)]"
            />
            띄어쓰기 복원
          </label>
          <label
            className="flex cursor-pointer items-center gap-2 text-sm text-muted"
            title="bbox 좌표로 단·행·표를 복원하고 읽는 순서를 잡습니다."
          >
            <input
              type="checkbox"
              checked={analyzeLayout}
              onChange={(e) => setAnalyzeLayout(e.target.checked)}
              className="accent-[var(--accent)]"
            />
            레이아웃 분석
          </label>
          <label
            className="flex cursor-pointer items-center gap-2 text-sm text-muted"
            title="텍스트 레이어가 있는 PDF도 강제로 OCR합니다. 두 경로를 비교할 때만 켜세요."
          >
            <input
              type="checkbox"
              checked={forceOcr}
              onChange={(e) => setForceOcr(e.target.checked)}
              className="accent-[var(--accent)]"
            />
            강제 OCR
          </label>
          <label
            className="flex cursor-pointer items-center gap-2 text-sm text-muted"
            title="뒤집힌 스캔을 바로잡아 주지만, 한글에서는 멀쩡한 줄을 180도 뒤집는 오작동이 있습니다."
          >
            <input
              type="checkbox"
              checked={useAngleCls}
              onChange={(e) => setUseAngleCls(e.target.checked)}
              className="accent-[var(--accent)]"
            />
            회전 보정
          </label>
          <span className="flex items-center gap-2 text-sm text-muted">
            <span
              className={`h-2 w-2 rounded-full ${
                online === null
                  ? "bg-muted"
                  : online
                    ? "bg-emerald-500"
                    : "bg-red-500"
              }`}
            />
            {online === null ? "확인 중" : online ? "엔진 연결됨" : "엔진 꺼짐"}
          </span>
        </div>
      </header>

      {!result && !loading && (
        <div className="flex flex-col gap-3">
          <Dropzone onFile={(f) => process(f)} disabled={loading} />
          <button
            onClick={runSample}
            className="self-center text-sm text-accent underline underline-offset-4"
          >
            샘플 이미지로 바로 해보기
          </button>
        </div>
      )}

      {error && (
        <div className="rounded-xl border border-red-500/40 bg-red-500/5 p-4 text-sm text-red-600 dark:text-red-400">
          {error}
        </div>
      )}

      {loading && (
        <div className="grid gap-6 lg:grid-cols-2">
          <div className="overflow-hidden rounded-xl border border-border bg-surface">
            {preview ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={preview} alt="처리 중인 이미지" className="w-full opacity-50" />
            ) : (
              <div className="h-72 animate-pulse bg-border/40" />
            )}
          </div>
          <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-border bg-surface p-10">
            <span className="h-6 w-6 animate-spin rounded-full border-2 border-border border-t-accent" />
            <p className="text-sm text-muted">텍스트를 인식하는 중입니다…</p>
          </div>
        </div>
      )}

      {result && !loading && (
        <>
          <div className="grid min-h-0 flex-1 gap-6 lg:grid-cols-2">
            <div className="min-w-0">
              <ImageCanvas
                result={result}
                page={page}
                onPageChange={setPage}
                activeId={activeId}
                activeBlockId={activeBlockId}
                highlightIds={highlightIds}
                onHover={setActiveId}
                onSelect={setActiveId}
                onHoverBlock={setActiveBlockId}
              />
            </div>
            <div className="min-h-0 lg:max-h-[calc(100vh-14rem)]">
              <ResultPanel
                result={result}
                page={page}
                activeId={activeId}
                activeBlockId={activeBlockId}
                extractReady={extractReady}
                onHover={setActiveId}
                onHoverBlock={setActiveBlockId}
                onHighlight={setHighlightIds}
              />
            </div>
          </div>

          <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4 text-xs text-muted">
            <span className="font-mono">
              {result.filename} · {result.engine}
            </span>
            <button
              onClick={() => {
                setResult(null);
                setPreview(null);
              }}
              className="rounded-lg border border-border px-3 py-1.5 text-sm text-foreground transition hover:border-accent"
            >
              다른 파일 넣기
            </button>
          </footer>
        </>
      )}
    </main>
  );
}
