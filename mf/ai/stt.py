"""STT-адаптер: один интерфейс transcribe(path) → {text, language, duration, engine}.
Основной движок — faster-whisper локально (GPU; модель и тип вычислений из .env), запасной — OpenAI whisper-1
(MF_STT=openai или если локальная модель не поднялась и есть ключ). Аудио удаляет вызывающий код после расшифровки."""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

log = logging.getLogger("mf.ai.stt")

MODE = os.environ.get("MF_STT", "faster-whisper").strip().lower()          # faster-whisper | openai | off
WHISPER_MODEL = os.environ.get("MF_WHISPER_MODEL", "large-v3-turbo")       # выбор по tools/stt_bench.py → docs/STATUS.md
WHISPER_COMPUTE = os.environ.get("MF_WHISPER_COMPUTE", "int8_float16")
WHISPER_DEVICE = os.environ.get("MF_WHISPER_DEVICE", "auto")               # auto | cuda | cpu
LANGUAGE = os.environ.get("MF_STT_LANGUAGE", "").strip() or None           # пусто — автоопределение (ru/kk)

_model = None
_model_error: str | None = None
_lock = threading.Lock()


class STTError(Exception):
    pass


_preloaded = False


def preload_cuda_libs() -> list[str]:
    """cuBLAS 12 и cuDNN 9 ставятся pip-колёсами nvidia-*-cu12 в site-packages, а не в системный путь загрузчика:
    без предзагрузки ctranslate2 падает с «libcublas.so.12 is not found». Грузим их через ctypes RTLD_GLOBAL."""
    global _preloaded
    if _preloaded:
        return []
    import ctypes
    import importlib.util
    loaded = []
    for pkg, order in (("nvidia.cublas", ("libcublasLt", "libcublas", "libnvblas")),
                       ("nvidia.cudnn", ("libcudnn_graph", "libcudnn_engines_precompiled", "libcudnn_engines_runtime_compiled",
                                         "libcudnn_heuristic", "libcudnn_ops", "libcudnn_adv", "libcudnn_cnn", "libcudnn"))):
        spec = importlib.util.find_spec(pkg)
        if not spec or not spec.submodule_search_locations:
            continue
        lib = Path(list(spec.submodule_search_locations)[0]) / "lib"
        files = sorted(lib.glob("*.so*"), key=lambda f: next((i for i, n in enumerate(order) if f.name.startswith(n + ".")), 99))
        for f in files:
            try:
                ctypes.CDLL(str(f), mode=ctypes.RTLD_GLOBAL)
                loaded.append(f.name)
            except OSError as e:
                log.debug("preload %s: %s", f.name, e)
    _preloaded = True
    return loaded


def available() -> dict:
    """Что реально доступно — для /api/ai/status и честной плашки в интерфейсе."""
    local = MODE == "faster-whisper" and _model_error is None
    if local:
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            local = False
    return {"mode": MODE, "local": local, "local_model": WHISPER_MODEL if local else None,
            "openai": bool(os.environ.get("OPENAI_API_KEY")), "loaded": _model is not None, "error": _model_error}


def _load():
    global _model, _model_error
    with _lock:
        if _model is not None:
            return _model
        try:
            preload_cuda_libs()
            from faster_whisper import WhisperModel
            device = WHISPER_DEVICE
            if device == "auto":
                import ctranslate2
                device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
            compute = WHISPER_COMPUTE if device == "cuda" else "int8"
            t0 = time.time()
            _model = WhisperModel(WHISPER_MODEL, device=device, compute_type=compute)
            log.info("faster-whisper %s/%s на %s загружена за %.1f с", WHISPER_MODEL, compute, device, time.time() - t0)
            _model_error = None
        except Exception as e:   # noqa: BLE001
            _model_error = f"{type(e).__name__}: {e}"[:300]
            log.exception("faster-whisper не загрузилась")
            raise STTError(_model_error) from e
        return _model


def warmup() -> None:
    """Прогрев при старте сервера (в фоне), чтобы первая запись не ждала загрузку модели."""
    if MODE == "faster-whisper":
        try:
            _load()
        except STTError:
            pass


def _local(path: Path, language: str | None) -> dict:
    model = _load()
    t0 = time.time()
    segments, info = model.transcribe(str(path), language=language, beam_size=5, vad_filter=True,
                                      vad_parameters={"min_silence_duration_ms": 500})
    lines = []
    for s in segments:
        txt = s.text.strip()
        if txt:
            lines.append(txt)
    return {"text": "\n".join(lines), "language": info.language, "duration": round(info.duration, 1),
            "engine": f"faster-whisper:{WHISPER_MODEL}", "seconds": round(time.time() - t0, 1)}


def _openai(path: Path, language: str | None) -> dict:
    if not os.environ.get("OPENAI_API_KEY"):
        raise STTError("OPENAI_API_KEY не задан — облачный STT недоступен")
    from openai import OpenAI
    t0 = time.time()
    with open(path, "rb") as f:
        kwargs = {"model": "whisper-1", "file": f, "response_format": "verbose_json"}
        if language:
            kwargs["language"] = language
        r = OpenAI().audio.transcriptions.create(**kwargs)
    text = "\n".join(s.text.strip() if hasattr(s, "text") else s["text"].strip() for s in (getattr(r, "segments", None) or [])) or r.text
    return {"text": text, "language": getattr(r, "language", None) or language, "duration": round(float(getattr(r, "duration", 0) or 0), 1),
            "engine": "openai:whisper-1", "seconds": round(time.time() - t0, 1)}


def transcribe(path: str | Path, language: str | None = None) -> dict:
    """Локально, при сбое — облако (если есть ключ). MODE=off → STTError (остаётся текстовая расшифровка)."""
    path = Path(path)
    if not path.is_file() or path.stat().st_size < 1000:
        raise STTError("Аудио пустое или слишком короткое")
    language = language or LANGUAGE
    if MODE == "off":
        raise STTError("STT выключен (MF_STT=off) — вставьте текстовую расшифровку")
    if MODE == "openai":
        return _openai(path, language)
    try:
        return _local(path, language)
    except STTError as e:
        if os.environ.get("OPENAI_API_KEY"):
            log.warning("локальный STT недоступен (%s) — пробуем OpenAI whisper-1", e)
            return _openai(path, language)
        raise
