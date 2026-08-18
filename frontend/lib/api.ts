import type {
  ExtractPreset,
  ExtractResult,
  LangCode,
  OCRResult,
} from "./types";

// vercel.json이 /api/*를 backend 서비스로 rewrite하므로 배포 환경에서는
// 같은 도메인 상대경로를 쓴다. 로컬 개발(next dev)에는 rewrite가 없어 절대주소가 필요.
const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ??
  (process.env.NODE_ENV === "production" ? "" : "http://127.0.0.1:8000");

export interface OCROptions {
  lang: LangCode;
  /** 각도 분류기. 한글에서는 오작동이 있어 기본 off (README 참고) */
  useAngleCls: boolean;
  /** 인식 모델이 흘린 공백을 원본 픽셀 기준으로 복원 */
  restoreSpacing: boolean;
  /** 좌표로 단·표를 복원하고 읽는 순서를 잡음 */
  analyzeLayout: boolean;
  /** 텍스트 레이어가 있는 PDF도 강제로 OCR (비교용) */
  forceOcr: boolean;
}

export async function requestOCR(
  file: File | Blob,
  options: OCROptions,
  filename = "upload",
): Promise<OCRResult> {
  const form = new FormData();
  form.append("file", file, file instanceof File ? file.name : filename);
  form.append("lang", options.lang);
  form.append("use_angle_cls", String(options.useAngleCls));
  form.append("restore_spacing", String(options.restoreSpacing));
  form.append("analyze_layout", String(options.analyzeLayout));
  form.append("force_ocr", String(options.forceOcr));

  const res = await fetch(`${API_BASE}/api/ocr`, { method: "POST", body: form });

  if (!res.ok) {
    const detail = await res
      .json()
      .then((d) => d.detail as string)
      .catch(() => null);
    throw new Error(detail ?? `요청 실패 (${res.status})`);
  }
  return res.json();
}

export interface Health {
  online: boolean;
  /** LLM 항목 추출을 쓸 수 있는지 (백엔드에 API 키가 있는지) */
  extractReady: boolean;
}

export async function checkHealth(): Promise<Health> {
  try {
    const res = await fetch(`${API_BASE}/api/health`, { cache: "no-store" });
    if (!res.ok) return { online: false, extractReady: false };
    const body = await res.json();
    return { online: true, extractReady: Boolean(body.extract_ready) };
  } catch {
    return { online: false, extractReady: false };
  }
}

export async function requestExtract(
  result: OCRResult,
  preset: ExtractPreset,
): Promise<ExtractResult> {
  const res = await fetch(`${API_BASE}/api/extract`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      // 이미지는 보내지 않는다 — 추출에 필요한 건 텍스트와 줄 번호뿐이다.
      lines: result.lines.map((l) => ({ id: l.id, text: l.text, page: l.page })),
      markdown: result.markdown,
      preset,
    }),
  });

  if (!res.ok) {
    const detail = await res
      .json()
      .then((d) => d.detail as string)
      .catch(() => null);
    throw new Error(detail ?? `추출 실패 (${res.status})`);
  }
  return res.json();
}
