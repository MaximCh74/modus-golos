#!/usr/bin/env python3
"""Схематичная карта для панели директора: контуры стран из Natural Earth (public domain, 50m) в SVG без внешних тайлов
(CSP без сторонних источников, работает офлайн). Проекция — равнопромежуточная, окно lon 44…92, lat 38…64 → 900×520.
Запуск: python3 tools/make_map.py <ne_50m_admin_0_countries.geojson> > web/a/img/map.svg
Маркеры рисует web/a/mapview.js той же проекцией (константы ниже должны совпадать с MAP в mapview.js)."""
from __future__ import annotations

import json
import sys

LON0, LON1, LAT0, LAT1 = 44.0, 92.0, 38.0, 64.0
W, H = 900, 520
HIGHLIGHT = {"Kazakhstan": "#e6edf6", "Russia": "#eef2f7"}


def proj(lon: float, lat: float) -> tuple[float, float]:
    return (lon - LON0) / (LON1 - LON0) * W, (LAT1 - lat) / (LAT1 - LAT0) * H


def clip(poly: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Сазерленд — Ходжман: обрезка полигона прямоугольником окна (в координатах lon/lat)."""
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
            fill = HIGHLIGHT.get(name, "#f3f5f8")
            paths.append(f'<path d="{" ".join(d)}" fill="{fill}" stroke="#c9d1dc" stroke-width="0.8"><title>{name}</title></path>')
    print(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">')
    print(f'<rect width="{W}" height="{H}" fill="#dde7f3"/>')
    print("\n".join(paths))
    print("</svg>")


if __name__ == "__main__":
    main()
