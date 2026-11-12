"""Правила цвета владельца (12.11): красного текста нет нигде — красный только акцент (черта у заголовков, точка просрочки, метки на
карте, угол главной кнопки); подписи разделов тёмно-синие; ссылки — цвет системы, подчёркивание при наведении; ошибки — красная точка
и тёмный текст; ряд вкладок с затуханием, слова не режутся."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = (ROOT / "web" / "a" / "style.css").read_text(encoding="utf-8")
RED_TOKENS = ("--red", "--red-dark", "--brand", "--brand-dark", "--bad")
# цвет (currentColor) у иконок меток карты — это акцент, не текст
ICON_SELECTORS = (".marker", ".lg-pin")


def _rules():
    css = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        yield m.group(1).strip(), m.group(2)


def test_no_red_text_color_in_css():
    bad = []
    for sel, body in _rules():
        for d in body.split(";"):
            if ":" not in d:
                continue
            prop, val = (x.strip() for x in d.split(":", 1))
            if prop not in ("color", "-webkit-text-fill-color", "text-decoration-color"):
                continue
            red = any(re.search(rf"var\({re.escape(t)}\)", val) for t in RED_TOKENS) or re.search(r"#(e40000|bc262c|ed1111|ff0000|f00)\b", val, re.I)
            if red and not any(x in sel for x in ICON_SELECTORS):
                bad.append(f"{sel} {{ {prop}: {val} }}")
    assert not bad, bad


def test_labels_navy_links_system_color_errors_dot():
    rules = dict(_rules())
    assert "var(--navy)" in rules[".lbl"] and "var(--red)" in rules[".lbl::before"]   # подпись тёмно-синяя, красная черта осталась
    a = rules["a"]
    assert "var(--navy)" in a and "text-decoration: none" in a and "underline" in rules["a:hover"]
    assert "var(--red)" not in rules[".card-bad"] and "var(--red)" in rules[".card-bad::before"]
    assert "var(--bad)" not in rules[".toast.bad"] and "var(--red)" in rules[".toast.bad::before"]
    assert "flex: none" in rules[".tabs > a"] and "mask-image" in rules[".tabs.more-right"]


def test_points_is_chip_not_link():
    js = (ROOT / "web" / "a" / "app.js").read_text(encoding="utf-8")
    assert "class: 'chip chip-points'" in js
