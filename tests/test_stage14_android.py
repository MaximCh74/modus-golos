"""Пункт 5 очереди 12.11 — Android: Digital Asset Links на нашем домене для двух TWA-приложений (/app и /boss), манифесты PWA
согласованы с ними; подписанный APK лежит в demo/android (если собран на этой машине)."""
import json
import pathlib
import re
import zipfile

import pytest
from fastapi.testclient import TestClient

from mf.main import app

ROOT = pathlib.Path(__file__).resolve().parent.parent
PACKAGES = {"kz.cqsystems.modusgolos": "/app", "kz.cqsystems.modusgolos.boss": "/boss"}


@pytest.fixture(scope="module")
def c():
    with TestClient(app) as client:
        yield client


def test_assetlinks_served_for_both_packages(c):
    c.cookies.clear()
    r = c.get("/.well-known/assetlinks.json")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
    links = r.json()
    assert {l["target"]["package_name"] for l in links} == set(PACKAGES)
    for l in links:
        assert l["relation"] == ["delegate_permission/common.handle_all_urls"] and l["target"]["namespace"] == "android_app"
        fps = l["target"]["sha256_cert_fingerprints"]
        assert len(fps) == 1 and re.fullmatch(r"([0-9A-F]{2}:){31}[0-9A-F]{2}", fps[0]), fps
    assert len({l["target"]["sha256_cert_fingerprints"][0] for l in links}) == 1   # оба приложения подписаны одним ключом


def test_pwa_manifests_match_twa(c):
    m = c.get("/manifest.json").json()
    b = c.get("/manifest-boss.json").json()
    assert m["start_url"] == "/app" and b["start_url"] == "/boss" and b["scope"] == "/boss" and m["scope"] == "/"
    assert m["display"] == "standalone" and b["display"] == "standalone" and m["theme_color"] == b["theme_color"] == "#082742"
    for src in {i["src"] for i in m["icons"] + b["icons"]}:
        assert c.get(src).status_code == 200, src
    assert c.get("/boss").status_code == 200 and c.get("/app").status_code == 200


def test_signed_apks_in_demo():
    """APK собираются Bubblewrap вне репозитория (~/MODUS_ANDROID), подписанные копии кладутся в demo/android. Без них — пропуск."""
    d = ROOT / "demo" / "android"
    apks = sorted(d.glob("*.apk")) if d.is_dir() else []
    if not apks:
        pytest.skip("APK не собраны на этой машине (см. docs/ANDROID.md)")
    names = {p.name for p in apks}
    assert {"modus-golos.apk", "modus-golos-director.apk"} <= names, names
    for p in apks:
        with zipfile.ZipFile(p) as z:
            files = z.namelist()
            assert "AndroidManifest.xml" in files and any(f.startswith("META-INF/") and f.endswith((".RSA", ".EC")) for f in files), p.name   # подписан
        assert p.stat().st_size < 10 * 1024 * 1024
