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

def mode() -> str:
    """faster-whisper | openai | off — читается при каждом вызове (тесты и .env без перезапуска)."""
    return os.environ.get("MF_STT", "faster-whisper").strip().lower()


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
        try:
            spec = importlib.util.find_spec(pkg)
        except ModuleNotFoundError:   # нет пакета nvidia (Docker без GPU, ноутбук без CUDA-колёс) — грузить нечего
            continue
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
    local = mode() == "faster-whisper" and _model_error is None
    if local:
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            local = False
    return {"mode": mode(), "local": local, "local_model": WHISPER_MODEL if local else None,
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
    if mode() == "faster-whisper":
        try:
            _load()
        except STTError:
            pass


def name_hints() -> tuple[str, str]:
    """Имена демо-пользователей и термины компании для распознавания: hotwords + initial_prompt (faster-whisper ≥ 1.0.2),
    чтобы «Ерлан» не превращался в «Ирлан». Берутся из базы, поэтому новые сотрудники подхватываются сами."""
    try:
        from .. import db
        rows = db.q("SELECT name FROM users WHERE active=1")
        names = sorted({r["name"].split()[0] for r in rows} | {r["name"] for r in rows})
    except Exception:   # noqa: BLE001
        names = []
    first = sorted({n for n in names if " " not in n})
    terms = ["1С", "Битрикс24", "номенклатура", "спецификация"]
    # лимит промпта whisper — 224 токена: только имена (без фамилий) и четыре термина, не больше ~200 символов
    hot = ", ".join(first[:30])
    prompt = ("Планёрка «Модус Трейд»: " + ", ".join(first[:16]) + ". " + ", ".join(terms) + ".")[:200]
    return hot, prompt


def _local(path: Path, language: str | None, max_seconds: int | None = None) -> dict:
    model = _load()
    t0 = time.time()
    hot, prompt = name_hints()
    try:
        segments, info = model.transcribe(str(path), language=language, beam_size=5, vad_filter=True,
                                          vad_parameters={"min_silence_duration_ms": 500},
                                          hotwords=hot or None, initial_prompt=prompt or None,
                                          clip_timestamps=f"0,{int(max_seconds)}" if max_seconds else "0")   # F-07: голосовой ввод — не длиннее
        lines = []
        for s in segments:
            txt = s.text.strip()
            if txt:
                lines.append(txt)
    except STTError:
        raise
    except Exception as e:   # noqa: BLE001 — битый файл, неизвестный формат, сбой GPU
        raise STTError(f"не удалось расшифровать запись: {type(e).__name__}") from e
    return {"text": "\n".join(lines), "language": info.language, "duration": round(info.duration, 1),
            "engine": f"faster-whisper:{WHISPER_MODEL}", "seconds": round(time.time() - t0, 1)}


VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi", ".webm"}


def extract_audio(path: Path, max_seconds: int | None = None) -> Path:
    """Запись видеозвонка → m4a (ffmpeg, без видео): для whisper-1 (лимит 25 МБ) и на случай, если декодер не возьмёт контейнер.
    max_seconds — обрезать (голосовой ввод: не платим за лишние минуты)."""
    import subprocess
    out = path.with_suffix(".extracted.m4a")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k"]
    if max_seconds:
        cmd += ["-t", str(int(max_seconds))]
    try:
        subprocess.run(cmd + [str(out)], check=True, timeout=600)
    except Exception:
        out.unlink(missing_ok=True)   # F-16: недоделанный файл не остаётся
        raise
    return out


def _openai(path: Path, language: str | None, max_seconds: int | None = None) -> dict:
    if not os.environ.get("OPENAI_API_KEY"):
        raise STTError("OPENAI_API_KEY не задан — облачный STT недоступен")
    from openai import OpenAI
    from . import budget
    try:
        budget.spend("stt")
    except budget.Exhausted as e:
        raise STTError(str(e)) from e
    t0 = time.time()
    tmp = None
    try:
        if max_seconds or path.suffix.lower() in VIDEO_EXT or path.stat().st_size > 24 * 1024 * 1024:
            try:
                tmp = extract_audio(path, max_seconds)
                path = tmp
            except Exception as e:   # noqa: BLE001
                raise STTError(f"не удалось извлечь звук: {type(e).__name__}") from e
        _, prompt = name_hints()
        with open(path, "rb") as f:
            kwargs = {"model": "whisper-1", "file": f, "response_format": "verbose_json", "prompt": prompt}   # та же подсказка имён
            if language:
                kwargs["language"] = language
            r = OpenAI().audio.transcriptions.create(**kwargs)
    finally:
        if tmp:
            tmp.unlink(missing_ok=True)   # F-16: и при ошибке облака извлечённая дорожка не остаётся
    text = "\n".join(s.text.strip() if hasattr(s, "text") else s["text"].strip() for s in (getattr(r, "segments", None) or [])) or r.text
    return {"text": text, "language": getattr(r, "language", None) or language, "duration": round(float(getattr(r, "duration", 0) or 0), 1),
            "engine": "openai:whisper-1", "seconds": round(time.time() - t0, 1)}


def transcribe(path: str | Path, language: str | None = None, max_seconds: int | None = None) -> dict:
    """Локально, при сбое — облако (если есть ключ). MODE=off → STTError (остаётся текстовая расшифровка).
    max_seconds — распознать только начало записи (голосовой ввод в формах: 3 минуты в интерфейсе)."""
    path = Path(path)
    if not path.is_file() or path.stat().st_size < 1000:
        raise STTError("Аудио пустое или слишком короткое")
    language = language or LANGUAGE
    m = mode()
    if m == "off":
        raise STTError("STT выключен (MF_STT=off) — вставьте текстовую расшифровку")
    if m == "openai":
        return _openai(path, language, max_seconds)
    try:
        return _local(path, language, max_seconds)
    except STTError as e:
        if os.environ.get("OPENAI_API_KEY"):
            log.warning("локальный STT недоступен (%s) — пробуем OpenAI whisper-1", e)
            return _openai(path, language, max_seconds)
        raise
