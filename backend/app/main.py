"""OCR API 서버 (FastAPI)."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Annotated, get_args

import anyio
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from . import extract as extract_mod
from . import ocr
from .schemas import (
    ExtractRequest,
    ExtractResponse,
    HealthResponse,
    LangCode,
    OCRResponse,
)

logger = logging.getLogger("ocr-api")

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
ALLOWED_LANGS = set(get_args(LangCode))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 첫 요청이 5초씩 걸리지 않도록 기본 언어 모델을 미리 올려둔다.
    logger.info("한국어 OCR 모델 로딩 중...")
    await anyio.to_thread.run_sync(ocr.get_engine, "korean")
    logger.info("준비 완료")
    yield


app = FastAPI(title="OCR API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        engine=ocr.ENGINE_NAME,
        warm_langs=ocr.warm_langs(),
        extract_ready=bool(
            os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        ),
    )


@app.post("/api/ocr", response_model=OCRResponse)
async def run_ocr(
    file: Annotated[UploadFile, File()],
    lang: Annotated[str, Form()] = "korean",
    use_angle_cls: Annotated[bool, Form()] = False,
    restore_spacing: Annotated[bool, Form()] = True,
    analyze_layout: Annotated[bool, Form()] = True,
    force_ocr: Annotated[bool, Form()] = False,
) -> OCRResponse:
    if lang not in ALLOWED_LANGS:
        raise HTTPException(400, f"지원하지 않는 언어입니다: {lang}")

    data = await file.read()
    if not data:
        raise HTTPException(400, "빈 파일입니다.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "파일이 너무 큽니다. (최대 20MB)")

    try:
        # OCR은 CPU를 오래 쓰는 동기 작업이라 threadpool로 넘긴다.
        return await anyio.to_thread.run_sync(
            ocr.run_ocr,
            data,
            file.content_type,
            file.filename or "upload",
            lang,
            use_angle_cls,
            restore_spacing,
            analyze_layout,
            force_ocr,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("OCR 실패")
        raise HTTPException(422, f"이미지를 읽을 수 없습니다: {exc}") from exc


@app.post("/api/extract", response_model=ExtractResponse)
async def extract(request: ExtractRequest) -> ExtractResponse:
    if not request.lines:
        raise HTTPException(400, "추출할 텍스트가 없습니다.")

    try:
        # LLM 호출은 수 초 걸리는 동기 작업이라 threadpool로 넘긴다.
        return await anyio.to_thread.run_sync(
            extract_mod.extract, request.lines, request.markdown, request.preset
        )
    except extract_mod.MissingAPIKey as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        logger.exception("항목 추출 실패")
        raise HTTPException(502, f"추출에 실패했습니다: {exc}") from exc
