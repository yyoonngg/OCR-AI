export type LangCode = "korean" | "ch" | "en" | "japan" | "latin";

export interface BBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface TextLine {
  id: number;
  /** 띄어쓰기 복원까지 끝난 최종 텍스트 */
  text: string;
  /** 인식 모델이 그대로 내놓은 원본 */
  raw_text: string;
  spacing_fixed: boolean;
  confidence: number;
  /** 기울어진 텍스트까지 감싸는 4점 다각형 (이미지 픽셀 좌표) */
  polygon: [number, number][];
  bbox: BBox;
  page: number;
  block_id: number | null;
  /** 읽는 순서. 검출 순서(id)와 다를 수 있다 */
  reading_index: number | null;
}

export interface Cell {
  row: number;
  column: number;
  text: string;
  line_ids: number[];
  bbox: BBox;
}

export interface LayoutBlock {
  id: number;
  kind: "text" | "table";
  page: number;
  /** 2단 편집일 때 몇 번째 단인지 (0부터) */
  page_column: number;
  bbox: BBox;
  text: string;
  line_ids: number[];
  rows: number;
  columns: number;
  has_header: boolean;
  cells: Cell[];
}

export type PageSource = "ocr" | "pdf_text";

export interface PageInfo {
  page: number;
  width: number;
  height: number;
  image_data_url: string;
  /** pdf_text면 OCR 없이 PDF 텍스트 레이어에서 읽은 것 */
  source: PageSource;
}

export type QualityLevel = "good" | "fair" | "poor";

export interface QualityReport {
  level: QualityLevel;
  avg_confidence: number;
  /** 줄 높이 중앙값(px). 작을수록 위험하다 */
  median_line_height: number;
  low_confidence_lines: number;
  notes: string[];
}

export interface Timing {
  detect_ms: number;
  classify_ms: number;
  recognize_ms: number;
  spacing_ms: number;
  rules_ms: number;
  layout_ms: number;
  total_ms: number;
}

export interface OCRResult {
  filename: string;
  lang: LangCode;
  pages: PageInfo[];
  lines: TextLine[];
  blocks: LayoutBlock[];
  /** 읽는 순서대로 정렬된 텍스트 */
  full_text: string;
  /** 띄어쓰기 복원 전, 검출 순서 그대로의 텍스트. 비교용 */
  raw_text: string;
  /** 표를 파이프 표로 살린 마크다운 */
  markdown: string;
  spacing_fixed_lines: number;
  quality: QualityReport;
  table_count: number;
  page_columns: number;
  timing: Timing;
  engine: string;
}

// --- 항목 추출 (LLM) ---

export type ExtractPreset = "auto" | "invoice";
export type Confidence = "high" | "medium" | "low";

export interface ExtractedField {
  key: string;
  value: string;
  /** 근거가 된 OCR 줄. 화면에서 원본 위치를 짚어준다 */
  line_ids: number[];
  confidence: Confidence;
}

export interface LineItem {
  name: string;
  quantity: string;
  unit_price: string;
  amount: string;
  line_ids: number[];
}

export interface ExtractUsage {
  model: string;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  elapsed_ms: number;
}

export interface ExtractResult {
  preset: ExtractPreset;
  doc_type: string;
  fields: ExtractedField[];
  items: LineItem[];
  warnings: string[];
  usage: ExtractUsage;
}

export const PRESET_OPTIONS: { value: ExtractPreset; label: string }[] = [
  { value: "auto", label: "자동 판별" },
  { value: "invoice", label: "거래명세서·영수증" },
];

export const LANG_OPTIONS: { value: LangCode; label: string }[] = [
  { value: "korean", label: "한국어" },
  { value: "en", label: "영어" },
  { value: "ch", label: "중국어" },
  { value: "japan", label: "일본어" },
  { value: "latin", label: "라틴 문자" },
];
