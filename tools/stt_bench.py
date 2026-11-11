#!/usr/bin/env python3
"""Сравнение моделей faster-whisper для выбора STT (этап 2, ответ Марка п. 2):
`medium` против `large-v3-turbo` на короткой русской и короткой казахской фразе, int8_float16 и int8 на GPU.
Критерий: влезает в 6 ГБ VRAM и лучше пишет казахский. Тестовые фразы синтезируются edge-tts (голоса Microsoft,
без ключа). Запуск: python3 tools/stt_bench.py [--out результат.json]. Результат — в docs/STATUS.md."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path

PHRASES = {
    "ru": ("ru-RU-DmitryNeural", "Коллеги, коротко. Бухгалтерия снова пишет про повторный ввод: одни и те же данные вбивают "
                                 "в две системы. Ерлан, до пятницы собери список операций и покажи."),
    "kk": ("kk-KZ-DauletNeural", "Әріптестер, қысқаша айтайын. Бухгалтерия қайта енгізу туралы тағы жазып отыр: бір деректерді "
                                 "екі жүйеге енгізеді. Ерлан, жұма күніне дейін операциялар тізімін жинап көрсет."),
}
MODELS = ["medium", "large-v3-turbo"]
COMPUTE = ["int8_float16", "int8"]


def vram_used_mb() -> int:
    out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], capture_output=True, text=True)
    return int(out.stdout.strip().splitlines()[0])


def synth(workdir: Path) -> dict[str, Path]:
    files = {}
    for lang, (voice, text) in PHRASES.items():
        mp3, wav = workdir / f"{lang}.mp3", workdir / f"{lang}.wav"
        if not wav.exists():
            subprocess.run([sys.executable, "-m", "edge_tts", "--voice", voice, "--text", text, "--write-media", str(mp3)], check=True)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-ac", "1", "-ar", "16000", str(wav)], check=True)
        files[lang] = wav
    return files


def norm(s: str) -> str:
    return " ".join("".join(ch.lower() for ch in s if ch.isalnum() or ch.isspace()).split())


def similarity(a: str, b: str) -> float:
    return round(SequenceMatcher(None, norm(a), norm(b)).ratio(), 3)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="stt_bench.json")
    ap.add_argument("--work", default=str(Path(__file__).resolve().parent.parent / "var" / "stt_bench"))
    ap.add_argument("--models", nargs="*", default=MODELS)
    ap.add_argument("--compute", nargs="*", default=COMPUTE)
    args = ap.parse_args()
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    files = synth(work)
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from mf.ai.stt import preload_cuda_libs
    print("предзагружены:", ", ".join(preload_cuda_libs()) or "ничего (ставьте nvidia-cublas-cu12 / nvidia-cudnn-cu12)")
    from faster_whisper import WhisperModel

    results = []
    base_vram = vram_used_mb()
    print(f"VRAM до загрузки: {base_vram} МБ")
    for model_name in args.models:
        for compute in args.compute:
            print(f"\n=== {model_name} / {compute} ===", flush=True)
            t0 = time.time()
            try:
                model = WhisperModel(model_name, device="cuda", compute_type=compute)
            except Exception as e:   # noqa: BLE001
                print("  не загрузилась:", e)
                results.append({"model": model_name, "compute": compute, "error": str(e)[:300]})
                continue
            load_s = round(time.time() - t0, 1)
            row = {"model": model_name, "compute": compute, "load_s": load_s, "langs": {}}
            peak = vram_used_mb()
            for lang, wav in files.items():
                t1 = time.time()
                segments, info = model.transcribe(str(wav), language=lang, beam_size=5, vad_filter=False)
                text = " ".join(s.text.strip() for s in segments)
                dt = round(time.time() - t1, 2)
                peak = max(peak, vram_used_mb())
                sim = similarity(text, PHRASES[lang][1])
                row["langs"][lang] = {"text": text, "seconds": dt, "similarity": sim, "audio_s": round(info.duration, 1)}
                print(f"  [{lang}] {dt} с, схожесть {sim}: {text}", flush=True)
            # автоопределение языка на казахской фразе — пишет ли модель казахский без подсказки
            segs, info = model.transcribe(str(files["kk"]), beam_size=5)
            auto_text = " ".join(s.text.strip() for s in segs)
            row["kk_autodetect"] = {"language": info.language, "prob": round(info.language_probability, 2), "text": auto_text,
                                    "similarity": similarity(auto_text, PHRASES["kk"][1])}
            print(f"  [kk, авто] язык={info.language} p={info.language_probability:.2f}: {auto_text}", flush=True)
            row["vram_peak_mb"] = peak - base_vram
            print(f"  загрузка {load_s} с, VRAM пик +{row['vram_peak_mb']} МБ", flush=True)
            results.append(row)
            del model
            import gc; gc.collect()
            time.sleep(2)
    Path(args.out).write_text(json.dumps({"phrases": {k: v[1] for k, v in PHRASES.items()}, "results": results}, ensure_ascii=False, indent=2))
    print("\nитог →", args.out)


if __name__ == "__main__":
    main()
