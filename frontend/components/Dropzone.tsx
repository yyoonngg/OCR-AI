"use client";

import { useCallback, useEffect, useRef, useState } from "react";

interface Props {
  onFile: (file: File) => void;
  disabled?: boolean;
}

const ACCEPT = "image/png,image/jpeg,image/webp,image/bmp,image/tiff,application/pdf";

export default function Dropzone({ onFile, disabled }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  // 스크린샷을 바로 붙여넣는 흐름이 실제로 가장 많이 쓰인다.
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      if (disabled) return;
      const item = Array.from(e.clipboardData?.items ?? []).find((i) =>
        i.type.startsWith("image/"),
      );
      const file = item?.getAsFile();
      if (file) onFile(file);
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, [onFile, disabled]);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      if (disabled) return;
      const file = e.dataTransfer.files?.[0];
      if (file) onFile(file);
    },
    [onFile, disabled],
  );

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      onClick={() => !disabled && inputRef.current?.click()}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") inputRef.current?.click();
      }}
      className={`flex flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed p-10 text-center transition
        ${disabled ? "cursor-not-allowed opacity-60" : "cursor-pointer hover:border-accent"}
        ${dragging ? "border-accent bg-accent/5" : "border-border bg-surface"}`}
    >
      <svg
        viewBox="0 0 24 24"
        className="h-9 w-9 text-muted"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden
      >
        <path d="M12 16V4m0 0L8 8m4-4 4 4" />
        <path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" />
      </svg>
      <div>
        <p className="font-medium">이미지를 끌어다 놓거나 클릭해서 선택하세요</p>
        <p className="mt-1 text-sm text-muted">
          PNG · JPG · WEBP · TIFF · PDF(최대 5쪽) — 클립보드 붙여넣기(⌘V)도 됩니다
        </p>
      </div>
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT}
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) onFile(file);
          e.target.value = ""; // 같은 파일을 다시 골라도 change가 발생하도록
        }}
      />
    </div>
  );
}
