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


def test_points_gold_star_without_frame():
    """Баллы (13.11): залитая золотистая звезда (свой токен) и число — без рамки и подложки; на главной по нажатию — профиль."""
    js = (ROOT / "web" / "a" / "app.js").read_text(encoding="utf-8")
    assert "pointsTag(pts.balance, '#/u/' + ME.id, 'pts-home')" in js and "chip-points" not in js
    rules = dict(_rules())
    assert "--gold:" in CSS and "var(--gold)" in rules[".star-gold"]
    assert "border" not in rules[".pts"] and "background" not in rules[".pts"]
    bell = rules[".bell .n"]
    assert "background: var(--red)" in bell and "color: var(--white)" in bell   # счётчик — красный кружок с белой цифрой


def test_app_icons_from_logo_mark():
    """Иконки из SVG-знака (tools/make_icons.py): «Модус Голос» — знак на белом, «Директор» — знак и тёмно-синяя с красной волна внизу;
    180 (apple-touch-icon), 192, 512 и maskable."""
    from PIL import Image
    d = ROOT / "web" / "a" / "img" / "icons"
    for name, sizes in (("icon", (180, 192, 512)), ("maskable", (192, 512)), ("boss", (180, 192, 512)), ("boss-maskable", (192, 512))):
        for s in sizes:
            im = Image.open(d / f"{name}-{s}.png").convert("RGB")
            assert im.size == (s, s), (name, s)
    app = Image.open(d / "icon-512.png").convert("RGB")
    assert app.getpixel((8, 8)) == (255, 255, 255) and app.getpixel((256, 504)) == (255, 255, 255)   # белый фон, без своей рамки
    boss = Image.open(d / "boss-512.png").convert("RGB")
    assert boss.getpixel((256, 500)) == (8, 39, 66)   # тёмно-синяя волна внизу
    assert any(boss.getpixel((x, y))[0] > 200 and boss.getpixel((x, y))[1] < 60 for x in range(0, 512, 8) for y in range(360, 440, 2))   # красная волна
    for html in (ROOT / "web").glob("*.html"):
        t = html.read_text(encoding="utf-8")
        if "apple-touch-icon" in t:
            assert "-180.png" in t, html.name
