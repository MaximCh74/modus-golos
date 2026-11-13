#!/usr/bin/env python3
"""Схематичная карта для стартовой и панели директора: контуры стран из Natural Earth (public domain, 50m) в SVG без внешних
тайлов (CSP без сторонних источников, работает офлайн). Рамка — полоса городов заказчика Самара — Тюмень — Омск — Астана — Павлодар
с небольшим запасом (lon 45…82, lat 46.5…60.5; Атырау и объекты южнее ещё видны); страны целиком не рисуем — только то, что внутри рамки,
контуры тонкие и спокойные. Проекция равнопромежуточная со сжатием по долготе cos(54°), чтобы фигуры не были растянуты.
Запуск: python3 tools/make_map.py <ne_50m_admin_0_countries.geojson> [ne_50m_admin_1_states_provinces_lines.geojson] > web/a/img/map.svg
Второй файл (необязательный) — границы регионов Natural Earth admin-1 (lines): едва заметная фактура внутри стран (этап 7).
Маркеры рисует web/a/mapview.js в процентах той же рамки (константы MAP там должны совпадать с LON0/LON1/LAT0/LAT1)."""
from __future__ import annotations

import json
import math
import sys

LON0, LON1, LAT0, LAT1 = 45.0, 82.0, 46.5, 60.5
# карта директора (замечание владельца 13.11): больше России сверху — от Самары с запасом (46° в. д.) до востока за Павлодаром (86°),
# с севера до 62° с. ш., с юга с запасом под Атырау (45°): --frame 46,86,45,62 → web/a/img/map-director.svg
if "--frame" in sys.argv:
    i = sys.argv.index("--frame")
    LON0, LON1, LAT0, LAT1 = (float(x) for x in sys.argv[i + 1].split(","))
    del sys.argv[i:i + 2]
W = 900
KX = W / (LON1 - LON0)                      # px на градус долготы
MID = 54.0 if (LAT0, LAT1) == (46.5, 60.5) else (LAT0 + LAT1) / 2   # средняя широта рамки (у стартовой — 54°, как было)
KY = KX / math.cos(math.radians(MID))       # px на градус широты (сжатие по средней широте рамки)
H = round((LAT1 - LAT0) * KY)
# Замечание владельца 12.11: заливка стран заметно темнее воды и фона страницы, границы чёткие — на телефоне карта должна читаться.
# Казахстан — самый тёмный (фокус карты), Россия чуть светлее, остальные страны по краям — ещё светлее; вода светлая.
LAND, WATER, LINE = "#dfe5ed", "#eaf0f6", "#8593a6"
FILLS = {"Russia": "#d9e1ea", "Kazakhstan": "#cdd7e3"}
REGION_LINE = "#b9c3d0"                                   # линии регионов — видны, но тише границ стран


def proj(lon: float, lat: float) -> tuple[float, float]:
    return (lon - LON0) * KX, (LAT1 - lat) * KY


def clip(poly: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Сазерленд — Ходжман: обрезка полигона прямоугольником рамки (в координатах lon/lat)."""
    def inside(p, edge):
        k, v, sign = edge
        return (p[k] - v) * sign >= 0

    def intersect(a, b, edge):
        k, v, _ = edge
        t = (v - a[k]) / (b[k] - a[k])
        return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))

    out = poly
    for edge in ((0, LON0, 1), (0, LON1, -1), (1, LAT0, 1), (1, LAT1, -1)):
        inp, out = out, []
        if not inp:
            break
        s = inp[-1]
        for e in inp:
            if inside(e, edge):
                if not inside(s, edge):
                    out.append(intersect(s, e, edge))
                out.append(e)
            elif inside(s, edge):
                out.append(intersect(s, e, edge))
            s = e
    return out


def clip_line(pts: list[tuple[float, float]]) -> list[list[tuple[float, float]]]:
    """Ломаная → куски внутри рамки (точки вне рамки просто рвут линию; для едва заметной фактуры этого достаточно)."""
    out, cur = [], []
    for x, y in pts:
        if LON0 <= x <= LON1 and LAT0 <= y <= LAT1:
            cur.append((x, y))
        elif cur:
            out.append(cur); cur = []
    if cur:
        out.append(cur)
    return [c for c in out if len(c) >= 2]


def regions(path: str) -> str:
    data = json.load(open(path, encoding="utf-8"))
    d = []
    for f in data["features"]:
        geom = f["geometry"]
        lines = geom["coordinates"] if geom["type"] == "MultiLineString" else [geom["coordinates"]]
        for line in lines:
            for piece in clip_line([(float(x), float(y)) for x, y in line]):
                pts = [proj(x, y) for x, y in piece]
                d.append("M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts))
    return f'<path d="{" ".join(d)}" fill="none" stroke="{REGION_LINE}" stroke-width="0.6" stroke-linejoin="round" stroke-linecap="round"/>' if d else ""


def main() -> None:
    data = json.load(open(sys.argv[1], encoding="utf-8"))
    paths = []
    for f in data["features"]:
        name = f["properties"].get("ADMIN")
        geom = f["geometry"]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        d = []
        for poly in polys:
            ring = [(float(x), float(y)) for x, y in poly[0]]
            if max(x for x, _ in ring) < LON0 or min(x for x, _ in ring) > LON1 or max(y for _, y in ring) < LAT0 or min(y for _, y in ring) > LAT1:
                continue
            c = clip(ring)
            if len(c) < 3:
                continue
            pts = [proj(x, y) for x, y in c]
            d.append("M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + " Z")
        if d:
            paths.append(f'<path d="{" ".join(d)}" fill="{FILLS.get(name, LAND)}" stroke="{LINE}" stroke-width="1.1" stroke-linejoin="round"><title>{name}</title></path>')
    print(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">')
    print(f'<rect width="{W}" height="{H}" fill="{WATER}"/>')
    print("\n".join(paths))
    if len(sys.argv) > 2:
        print(regions(sys.argv[2]))
    print("</svg>")


def centroids(path: str, names=("Russia", "Kazakhstan")) -> dict:
    """Центр видимой части страны в рамке (центроид площади обрезанных полигонов) — туда ставится подпись страны."""
    data = json.load(open(path, encoding="utf-8"))
    out = {}
    for f in data["features"]:
        name = f["properties"].get("ADMIN")
        if name not in names:
            continue
        geom = f["geometry"]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        A = cx = cy = 0.0
        for poly in polys:
            c = clip([(float(x), float(y)) for x, y in poly[0]])
            for (x1, y1), (x2, y2) in zip(c, c[1:] + c[:1]):
                k = x1 * y2 - x2 * y1
                A += k; cx += (x1 + x2) * k; cy += (y1 + y2) * k
        if A:
            out[name] = (round(cy / (3 * A), 2), round(cx / (3 * A), 2))   # (lat, lng)
    return out


if __name__ == "__main__":
    if "--centroids" in sys.argv:
        sys.argv.remove("--centroids")
        print(json.dumps({"frame": [LON0, LON1, LAT0, LAT1], "size": [W, H], "centroids": centroids(sys.argv[1])}, ensure_ascii=False))
        sys.exit(0)
    main()
