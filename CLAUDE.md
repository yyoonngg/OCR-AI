# OCR Playground

한글 문서·스캔본 OCR 실험용 앱. AX 아이디어를 얹기 전에 기본 OCR이 어디까지 되고
어디서 깨지는지 확인하려고 만든 기준선(baseline).

```
backend/    FastAPI + RapidOCR (ONNX Runtime, CPU 전용, Python 3.13)
frontend/   Next.js 16 + React 19 + Tailwind v4
docs/       트러블슈팅 기록
```

자세한 설계와 성능 수치는 `README.md` 참고.

## 명령

```bash
# 백엔드 (8000). 항목 추출까지 쓰려면 ANTHROPIC_API_KEY를 export 하고 실행
cd backend && ./.venv/bin/python -m uvicorn app.main:app --reload --port 8000

# 프론트엔드 (3000)
cd frontend && npm run dev

# 회귀 테스트 — 이미지·모델·네트워크 없이 즉시 실행
cd backend && ./.venv/bin/python tests/test_layout.py
cd backend && ./.venv/bin/python tests/test_quality.py
cd backend && ./.venv/bin/python tests/test_pdftext.py
cd backend && ./.venv/bin/python tests/test_rules.py

# 프론트엔드 검사
cd frontend && npx tsc --noEmit && npm run lint && npm run build
```

백엔드는 `backend/.venv`를 쓴다. 시스템 파이썬이 3.14라 ML 휠이 없으므로
`python3.13`으로 만든 venv를 그대로 쓸 것.

## 트러블슈팅 기록 (중요)

**사소하지 않은 문제를 해결할 때마다 `docs/troubleshooting/`에 md 파일로 남긴다.**
이 프로젝트는 임계값 기반 휴리스틱이 많아서, 한쪽을 고치면 다른 쪽이 깨진다.
무엇을 시도했고 왜 안 됐는지가 남아 있지 않으면 같은 길을 다시 걷게 된다.

### 언제 쓰나

- 원인을 찾는 데 시도가 두 번 이상 필요했던 문제
- 사용자가 제보한 오작동
- 다른 수정이 만든 회귀
- 그럴듯한데 실제로는 안 되는 접근을 확인했을 때 (이게 특히 값어치 있다)

간단한 오타·빌드 오류는 남기지 않는다.

### 어떻게 쓰나

`docs/troubleshooting/NN-증상을-설명하는-한글-제목.md`. 번호는 이어서 붙인다.

```markdown
# 한 줄 증상

- 날짜: YYYY-MM-DD
- 대상: 파일/함수
- 상태: 해결 / 완화 / 미해결
- 제보: (있으면)

## 증상
실제 출력을 그대로 붙인다. 요약하지 말 것.

## 원인
왜 그렇게 됐는지. 가능하면 좌표·수치 같은 근거를 함께.

## 시도했지만 안 된 것
접근법과 **왜 안 됐는지**. 다음 사람이 같은 걸 다시 시도하지 않도록.

## 해결
바뀐 규칙과 핵심 코드 몇 줄.

## 검증
실측 수치. "잘 된다"가 아니라 before/after 숫자.

## 남은 것
알면서 안 고친 한계. 판단 근거도 함께.
```

작성 후 `docs/troubleshooting/README.md` 표에 한 줄 추가한다.
관련 문서끼리는 서로 링크한다 (04↔06처럼 원인-회귀 관계가 흔하다).

## 작업할 때

- **레이아웃(`backend/app/layout.py`)을 건드리면 반드시 `tests/test_layout.py`를 돌린다.**
  여기 있는 케이스는 전부 실제로 한 번씩 깨졌던 것들이다.
  품질 임계값(`app/quality.py`)은 `tests/test_quality.py`.
- **성능·품질 주장은 재고 나서 한다.** 이 프로젝트에서 "전처리 붙이면 되겠지",
  "기울기가 제일 문제겠지"가 둘 다 측정 앞에서 틀렸다. 지표를 만들 때는
  그 지표가 재려는 걸 재는지부터 확인한다 (docs/troubleshooting/10번).
- 임계값 상수는 파일 상단에 모아 두고 주석에 "무엇을 걸러내는지" 적는다.
- 회귀 확인은 최소한 이 조합으로: 거래명세서 샘플(`frontend/public/sample.png`),
  2단 문서, 표만 잘라낸 크롭, 전체 페이지 해상도.
  **저해상도에서만 확인하면 놓친다.**
- 오작동 제보를 받으면 추측하지 말고 **원본 파일부터 확보한다.**
  크롭 범위·해상도가 조금만 달라도 검출 결과가 달라진다.
