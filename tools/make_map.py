#!/usr/bin/env python3
"""Схематичная карта для стартовой и панели директора: контуры стран из Natural Earth (public domain, 50m) в SVG без внешних
тайлов (CSP без сторонних источников, работает офлайн). Рамка — полоса городов заказчика Самара — Тюмень — Омск — Астана — Павлодар
с небольшим запасом (lon 45…82, lat 46.5…60.5; Атырау и объекты южнее ещё видны); страны целиком не рисуем — только то, что внутри рамки,
контуры тонкие и спокойные. Проекция равнопромежуточная со сжатием по долготе cos(54°), чтобы фигуры не были растянуты.
Запуск: python3 tools/make_map.py <ne_50m_admin_0_countries.geojson> > web/a/img/map.svg
Маркеры рисует web/a/mapview.js в процентах той же рамки (константы MAP там должны совпадать с LON0/LON1/LAT0/LAT1)."""
from __future__ import annotations

import json
import math
import sys

LON0, LON1, LAT0, LAT1 = 45.0, 82.0, 46.5, 60.5
W = 900
KX = W / (LON1 - LON0)                      # px на градус долготы
KY = KX / math.cos(math.radians(54.0))      # px на градус широты (средняя широта полосы — 54°)
H = round((LAT1 - LAT0) * KY)
LAND, WATER, LINE = "#f6f8fb", "#e9eff6", "#c3cbd6"


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
            paths.append(f'<path d="{" ".join(d)}" fill="{LAND}" stroke="{LINE}" stroke-width="0.7" stroke-linejoin="round"><title>{name}</title></path>')
    print(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">')
    print(f'<rect width="{W}" height="{H}" fill="{WATER}"/>')
    print("\n".join(paths))
    print("</svg>")


if __name__ == "__main__":
    main()
