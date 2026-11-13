#!/usr/bin/env python3
"""Аватарки демо-сотрудников (замечание владельца 13.11, п. 2): синтетические фотопортреты, сгенерированные ИИ (OpenAI Images,
gpt-image-1.5), единый стиль — деловая одежда, светлый нейтральный фон, по пояс, мягкий свет; казахские и русские имена — внешность
соответственно; люди вымышленные. Директору («Сергей Михайлович» — имя реального человека заказчика) портрет не делаем: остаются инициалы.

Оригиналы 1024 px (PNG) — в папку вне репозитория (--originals), в репозиторий — квадрат 512 px JPEG: demo/avatars/u<id>-<хэш>.jpg и
manifest.json (модель, запрос, расход токенов, стоимость). --apply записывает имена файлов в users.avatar живой демо-базы (сервер отдаёт
их из demo/avatars, если в папке данных файла нет) — после этого прогрев и tools/demo_snapshot.sh. Ключ — из .env (OPENAI_API_KEY).
Запуск: python3 tools/make_avatars.py --originals <папка> [--only 6,17] [--apply | --apply-only]"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mf import config, db  # noqa: E402,F401  (config подтягивает .env)

OUT = ROOT / "demo" / "avatars"
MODEL = "gpt-image-1.5"
# цены gpt-image-1.5 за 1 млн токенов (developers.openai.com/api/docs/pricing, 13.11.2026): текст на входе $5, картинка на выходе $32,
# текст на выходе $10
PRICE = {"text_in": 5.0, "image_out": 32.0, "text_out": 10.0}
KZ, RU = "Kazakh (Central Asian)", "Russian (Eastern European)"
# id: (пол, внешность, возраст, одежда, приметы)
PEOPLE = {
    2: ("man", RU, 44, "a charcoal suit with a light blue shirt, no tie", "short brown hair, light stubble"),
    3: ("man", KZ, 31, "a navy blazer over a white shirt, no tie", "short black hair, thin rectangular glasses"),
    4: ("woman", KZ, 36, "a dark blue blazer over a white blouse", "long straight black hair"),
    5: ("man", RU, 41, "a grey suit, white shirt and burgundy tie", "short dark blond hair"),
    6: ("woman", KZ, 38, "a beige blazer over a cream blouse", "shoulder-length dark hair, small stud earrings"),
    7: ("woman", RU, 49, "a dark grey jacket over a light blouse", "short auburn bob haircut"),
    8: ("man", KZ, 45, "a dark suit with a light shirt, no tie", "short black hair with a little grey, neat short beard"),
    9: ("man", RU, 39, "a navy suit and white shirt", "short dark hair, glasses"),
    10: ("woman", RU, 42, "a teal blazer over a white top", "blonde hair in a low ponytail"),
    11: ("man", RU, 51, "a dark grey suit, white shirt and navy tie", "receding grey hair"),
    12: ("woman", RU, 33, "a black blazer over a light grey top", "light brown shoulder-length hair"),
    13: ("man", KZ, 35, "a navy suit and white shirt, no tie", "short black hair, clean-shaven"),
    14: ("woman", RU, 40, "a navy blazer over a white blouse", "dark brown hair pinned up, glasses"),
    15: ("man", RU, 34, "a dark blue sweater over a collared shirt", "short brown hair, short beard"),
    16: ("man", KZ, 28, "a light grey blazer over a white shirt", "short black hair"),
    17: ("woman", RU, 31, "a dark navy blazer over a white blouse", "chestnut wavy shoulder-length hair"),
    18: ("woman", KZ, 29, "a light grey blazer over a white top", "long black hair with bangs"),
    19: ("man", RU, 37, "a grey jacket over a white shirt", "short light brown hair, glasses"),
    20: ("woman", KZ, 32, "a burgundy blazer over a black top", "black hair in a neat bun"),
    21: ("man", RU, 30, "a navy suit, white shirt and dark tie", "short brown hair, clean-shaven"),
    22: ("woman", KZ, 27, "a navy cardigan over a white blouse", "long dark hair"),
    23: ("man", RU, 35, "a navy suit and white shirt, no tie", "short brown hair, neat full beard"),
    24: ("woman", KZ, 34, "a soft green blazer over a white top", "shoulder-length dark hair"),
    25: ("woman", KZ, 46, "a dark navy jacket over a light blouse, small pendant", "black hair in a neat low bun"),
    26: ("man", KZ, 38, "a dark grey blazer over a light blue shirt", "short black hair, short trimmed beard"),
    27: ("man", KZ, 47, "a neat dark work jacket over a collared shirt", "short greying black hair, moustache"),
    28: ("man", KZ, 25, "a navy work jacket over a light shirt", "short black hair, clean-shaven"),
}


def prompt_for(uid: int) -> str:
    sex, look, age, wear, extra = PEOPLE[uid]
    return (f"Photorealistic corporate headshot of a fictional {look} {sex}, about {age} years old, {extra}, wearing {wear}. "
            "Waist-up portrait, centered, facing the camera with a calm friendly expression. Neutral light grey studio background, "
            "soft diffused light, natural skin texture, 85mm lens look. Consistent professional company-portrait style. A fictional person, "
            "not resembling any real or famous person. No text, no logos, no watermark.")


def cost(u: dict) -> float:
    det = u.get("output_tokens_details") or {}
    img_out = det.get("image_tokens", u.get("output_tokens", 0))
    txt_out = det.get("text_tokens", 0)
    return (u.get("input_tokens", 0) * PRICE["text_in"] + img_out * PRICE["image_out"] + txt_out * PRICE["text_out"]) / 1e6


def generate(uid: int, originals: Path) -> dict:
    from openai import OpenAI
    from PIL import Image
    p = prompt_for(uid)
    t = time.time()
    r = OpenAI(timeout=240).images.generate(model=MODEL, prompt=p, size="1024x1024", quality="medium", n=1)
    raw = base64.b64decode(r.data[0].b64_json)
    (originals / f"u{uid}.png").write_bytes(raw)
    img = Image.open(io.BytesIO(raw)).convert("RGB").resize((512, 512), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88, optimize=True)
    data = buf.getvalue()
    name = f"u{uid}-{hashlib.sha256(data).hexdigest()[:10]}.jpg"
    for old in OUT.glob(f"u{uid}-*.jpg"):
        old.unlink()
    (OUT / name).write_bytes(data)
    u = r.usage.model_dump() if getattr(r, "usage", None) else {}
    return {"user_id": uid, "file": name, "model": MODEL, "size": "1024x1024 → 512", "quality": "medium", "prompt": p, "usage": u,
            "cost_usd": round(cost(u), 4), "seconds": round(time.time() - t, 1)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--originals", required=True)
    ap.add_argument("--only", default="")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--apply-only", action="store_true", help="без генерации: только записать имена файлов из manifest.json в базу")
    a = ap.parse_args()
    originals = Path(a.originals)
    originals.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    man_path = OUT / "manifest.json"
    manifest = json.loads(man_path.read_text(encoding="utf-8")) if man_path.is_file() else {"note": "", "items": {}}
    manifest["note"] = ("Синтетические портреты вымышленных людей, сгенерированы ИИ (OpenAI Images) для демо «Модус Голос». Директору портрет не "
                        "делался: «Сергей Михайлович» — имя реального человека заказчика.")
    ids = [] if a.apply_only else [int(x) for x in a.only.split(",") if x.strip()] or sorted(PEOPLE)
    with ThreadPoolExecutor(max_workers=4) as pool:
        for res in pool.map(lambda uid: generate(uid, originals), ids):
            manifest["items"][str(res["user_id"])] = res
            print(f"u{res['user_id']}: {res['file']} · {res['seconds']} с · ${res['cost_usd']}", flush=True)
    items = manifest["items"].values()
    manifest["total_cost_usd"] = round(sum(x["cost_usd"] for x in items), 4)
    man_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"всего портретов: {len(manifest['items'])}, стоимость: ${manifest['total_cost_usd']}")
    if a.apply or a.apply_only:
        for x in items:
            db.ex("UPDATE users SET avatar=? WHERE id=?", (x["file"], x["user_id"]))
        print("users.avatar обновлены:", len(manifest["items"]))


if __name__ == "__main__":
    main()
