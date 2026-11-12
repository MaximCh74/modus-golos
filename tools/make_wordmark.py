#!/usr/bin/env python3
"""«МОДУС ГОЛОС» векторными контурами букв из SVG-логотипа заказчика (замечание владельца 12.11, вечер) → web/a/modus-golos-wordmark.svg.
Шрифтом не совпадает один в один, поэтому буквы берутся из самого логотипа (web/a/img/logo.svg, текстовый путь «МОДУС ТРЕЙД»):
- «МОДУС» — контуры слова целиком, как в логотипе;
- «ГОЛОС»: О и С — из логотипа; Г — из их Т без левой части перекладины; Л — по образцу их Д: та же толщина штриха, те же углы и
  высота, без нижней перекладины (ножки продолжены до базовой линии).
Межбуквенные интервалы и шаг строк — как в логотипе; система координат та же (viewBox высотой 42), поэтому в шапке картинка той же
высоты, что логотип, даёт буквы один в один. Цвет — тёмно-синий логотипа. Запуск: python3 tools/make_wordmark.py"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGO = ROOT / "web" / "a" / "img" / "logo.svg"
OUT = ROOT / "web" / "a" / "modus-golos-wordmark.svg"
NAVY = "#082742"
TOK = re.compile(r"[MLHVCZ]|-?\d*\.?\d+(?:e-?\d+)?", re.I)


def parse(d: str) -> list[dict]:
    """Абсолютный путь M/L/H/V/C/Z → подконтуры: {'start': (x, y), 'segs': [('L', p) | ('C', c1, c2, p)]}."""
    toks = TOK.findall(d)
    i, subs, cur, pt, start, cmd = 0, [], None, (0.0, 0.0), None, None

    def num() -> float:
        nonlocal i
        v = float(toks[i]); i += 1; return v
    while i < len(toks):
        if toks[i].isalpha():
            cmd = toks[i]; i += 1
            if cmd == "Z":
                cur["closed"] = True; pt = start; cmd = None
                continue
        if cmd == "M":
            pt = (num(), num()); start = pt; cur = {"start": pt, "segs": []}; subs.append(cur); cmd = "L"
        elif cmd == "L":
            pt = (num(), num()); cur["segs"].append(("L", pt))
        elif cmd == "H":
            pt = (num(), pt[1]); cur["segs"].append(("L", pt))
        elif cmd == "V":
            pt = (pt[0], num()); cur["segs"].append(("L", pt))
        elif cmd == "C":
            c1 = (num(), num()); c2 = (num(), num()); pt = (num(), num()); cur["segs"].append(("C", c1, c2, pt))
        else:
            raise ValueError(f"неожиданный токен {toks[i]!r}")
    return subs


def points(sub: dict) -> list[tuple[float, float]]:
    out = [sub["start"]]
    for s in sub["segs"]:
        out.append(s[-1])
        if s[0] == "C":
            out.extend([s[1], s[2]])
    return out


def bbox(subs: list[dict]) -> tuple[float, float, float, float]:
    pts = [p for s in subs for p in points(s)]
    return min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)


def shift(sub: dict, dx: float, dy: float) -> dict:
    mv = lambda p: (p[0] + dx, p[1] + dy)
    return {"start": mv(sub["start"]), "segs": [("L", mv(s[1])) if s[0] == "L" else ("C", mv(s[1]), mv(s[2]), mv(s[3])) for s in sub["segs"]]}


def to_d(sub: dict) -> str:
    f = lambda p: f"{p[0]:.3f} {p[1]:.3f}"
    out = ["M" + f(sub["start"])]
    for s in sub["segs"]:
        out.append("L" + f(s[1]) if s[0] == "L" else "C" + f(s[1]) + " " + f(s[2]) + " " + f(s[3]))
    return "".join(out) + "Z"


def glyphs(subs: list[dict]) -> dict[str, list[dict]]:
    """Подконтуры логотипа → буквы: строка 1 «МОДУС», строка 2 «ТРЕЙД»; контур внутри чужого bbox — его отверстие (О, Д, Р), бреве — к Й."""
    boxes = [(s, bbox([s])) for s in subs]
    outer = [(s, b) for s, b in boxes if not any(o is not s and ob[0] <= b[0] and ob[1] <= b[1] and ob[2] >= b[2] and ob[3] >= b[3] for o, ob in boxes)]
    letters = []
    for s, b in outer:
        if b[3] - b[1] < 6:   # бреве над Й — не отдельная буква
            continue
        parts = [s] + [o for o, ob in boxes if o is not s and b[0] <= ob[0] and b[1] <= ob[1] and b[2] >= ob[2] and b[3] >= ob[3]]
        parts += [o for o, ob in boxes if ob[3] - ob[1] < 6 and b[0] <= (ob[0] + ob[2]) / 2 <= b[2] and ob[3] <= b[1] + 1]   # бреве
        letters.append((b, parts))
    line1 = sorted([x for x in letters if x[0][1] < 21], key=lambda x: x[0][0])
    line2 = sorted([x for x in letters if x[0][1] >= 21], key=lambda x: x[0][0])
    names = dict(zip("МОДУС", line1)) | dict(zip(("Т", "Р", "Е", "Й", "Д2"), line2))   # Д2 — Д второй строки (для Л берём Д из «МОДУС»)
    return {k: v[1] for k, v in names.items()}


def uniq(vals, tol: float = .05) -> list[float]:
    """Отсортированные значения без почти-дублей (в логотипе координаты одной кромки отличаются на тысячные)."""
    out: list[float] = []
    for v in sorted(vals):
        if not out or v - out[-1] > tol:
            out.append(v)
    return out


def make_g(t: list[dict]) -> list[dict]:
    """Г из Т: остаётся стойка и правая часть перекладины (срез по левой кромке стойки)."""
    sub = t[0]
    xs, ys = uniq(p[0] for p in points(sub)), uniq(p[1] for p in points(sub))
    bar_top, bar_bottom = ys[0], ys[1]
    stem_l, stem_r = xs[1], xs[2]   # стойка — средняя пара вертикалей
    right, bottom = xs[-1], ys[-1]
    pts = [(stem_l, bar_top), (right, bar_top), (right, bar_bottom), (stem_r, bar_bottom), (stem_r, bottom), (stem_l, bottom)]
    return [{"start": pts[0], "segs": [("L", p) for p in pts[1:]]}]


def make_l(d: list[dict]) -> list[dict]:
    """Л по образцу Д: внешний контур без нижней перекладины, наклонная левая ножка и правая стойка продолжены до базовой линии."""
    outer, hole = (d[0], d[1]) if bbox([d[0]])[2] - bbox([d[0]])[0] > bbox([d[1]])[2] - bbox([d[1]])[0] else (d[1], d[0])
    base = max(p[1] for p in points(outer))
    bar_top = sorted({p[1] for p in points(outer)})[-2]   # верх нижней перекладины = низ отверстия
    o = [outer["start"]] + [s[-1] for s in outer["segs"]]
    # внешняя левая ножка: отрезок, который приходит в точку (x, bar_top) снизу слева → продлить наклон до base
    seg_o = [(o[i - 1], o[i]) for i in range(1, len(o)) if abs(o[i][1] - bar_top) < 1e-6 and abs(o[i - 1][1] - bar_top) > 1][0]
    a, b = seg_o if seg_o[0][1] < seg_o[1][1] else (seg_o[1], seg_o[0])     # a — верх ножки, b — низ (на bar_top)
    k = (b[0] - a[0]) / (b[1] - a[1]); foot_out = (b[0] + k * (base - b[1]), base)
    h = [hole["start"]] + [s[-1] for s in hole["segs"]]
    seg_i = [(h[i - 1], h[i]) for i in range(1, len(h)) if (abs(h[i][1] - bar_top) < 1e-6) != (abs(h[i - 1][1] - bar_top) < 1e-6) and min(h[i - 1][0], h[i][0]) < (bbox([hole])[0] + bbox([hole])[2]) / 2][0]
    a2, b2 = seg_i if seg_i[0][1] < seg_i[1][1] else (seg_i[1], seg_i[0])
    k2 = (b2[0] - a2[0]) / (b2[1] - a2[1]); foot_in = (b2[0] + k2 * (base - b2[1]), base)
    right = max(p[0] for p in points(outer)); hole_r = max(p[0] for p in points(hole)); top = min(p[1] for p in points(outer))
    # обход: внешний верх (из Д, от верха левой ножки до правого верхнего угла), правая стойка вниз, низ стойки, внутренняя стойка вверх,
    # верх отверстия (из Д, в обратном порядке), внутренняя ножка вниз до базовой линии, низ ножки, внешняя ножка вверх.
    segs = []
    start = foot_out
    segs.append(("L", a))
    started = False
    for s in outer["segs"]:   # внешний контур Д от точки a до правого верхнего угла
        if started:
            segs.append(s)
            if s[-1] == (right, top):
                break
        elif s[-1] == a:
            started = True
    segs += [("L", (right, base)), ("L", (hole_r, base)), ("L", (hole_r, bar_top))]
    # отверстие Д: от (hole_r, bar_top) вверх по правой стороне, по верху к a2 — берём сегменты отверстия в его собственном порядке
    hs = hole["segs"]; hp = [hole["start"]] + [s[-1] for s in hs]
    i_r = [i for i, p in enumerate(hp) if abs(p[0] - hole_r) < 1e-6 and abs(p[1] - bar_top) < 1e-6][0]
    i_a = [i for i, p in enumerate(hp) if p == a2][0]
    if i_a > i_r:
        for i in range(i_r + 1, i_a + 1):
            segs.append(hs[i - 1])
    else:   # обход отверстия в обратную сторону
        for i in range(i_r, i_a, -1):
            s = hs[i - 1]
            segs.append(("L", hp[i - 1]) if s[0] == "L" else ("C", s[2], s[1], hp[i - 1]))
    segs += [("L", foot_in), ("L", foot_out)]
    return [{"start": start, "segs": segs}]


def main() -> None:
    svg = LOGO.read_text(encoding="utf-8")
    text_d = max(re.findall(r'<path[^>]*\sd="([^"]+)"', svg), key=len)
    g = glyphs(parse(text_d))
    x0 = bbox(g["М"])[0]
    dy = bbox(g["Т"])[1] - bbox(g["М"])[1]   # шаг строк логотипа
    gap = (bbox(g["Р"])[0] - bbox(g["Т"])[2] + bbox(g["Е"])[0] - bbox(g["Р"])[2]) / 2   # интервал между прямыми буквами
    line1 = [s for ch in "МОДУС" for s in g[ch]]
    # «ГОЛОС»: Г из Т, О и С — копии со строки 1, Л из Д; интервалы: как в логотипе, у круглых — чуть плотнее (как У→С / М→О там)
    gl = {"Г": make_g(g["Т"]), "О": [shift(s, 0, dy) for s in g["О"]], "Л": [shift(s, 0, dy) for s in make_l(g["Д"])], "С": [shift(s, 0, dy) for s in g["С"]]}
    gaps = {"ГО": gap * .62, "ОЛ": gap * .3, "ЛО": gap * .9, "ОС": gap * .62}
    x = x0; line2 = []; prev = None
    for ch in "ГОЛОС":
        parts = gl[ch]; b = bbox(parts)
        if prev:
            x += gaps[prev + ch]
        line2 += [shift(s, x - b[0], 0) for s in parts]
        x += b[2] - b[0]; prev = ch
    allp = line1 + line2
    bx = bbox(allp)
    w = round(bx[2] - x0 + .5, 2)
    d = "".join(to_d(shift(s, -x0 + .25, 0)) for s in allp)
    OUT.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="42" viewBox="0 0 {w} 42" fill="none" role="img" aria-label="Модус Голос">\n'
                   f'<path fill-rule="evenodd" clip-rule="evenodd" d="{d}" fill="{NAVY}"/>\n</svg>\n', encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)}: {w}×42, строки y {bx[1]:.2f}…{bx[3]:.2f}, шаг строк {dy:.2f}, интервал {gap:.2f}")


if __name__ == "__main__":
    main()
