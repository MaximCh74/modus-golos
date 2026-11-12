"""Замечания владельца после теста с телефона (12.11): голос помощника, «Директор в кармане» — вопрос не превращается в команду,
ответы сходятся с плитками, ссылки открываются внутри /boss."""
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from mf import db
from mf.main import app


@pytest.fixture(scope="module")
def c():
    with TestClient(app) as client:
        yield client


def login(c, uid):
    c.cookies.clear()
    assert c.post("/api/auth/login-as", json={"user_id": uid}).status_code == 200


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="нет ffmpeg")
def test_tts_speed_up_ten_percent(tmp_path):
    from mf.ai import llm
    src = tmp_path / "a.mp3"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=5", "-b:a", "64k", str(src)], check=True)
    out = tmp_path / "b.mp3"
    out.write_bytes(llm.faster(src.read_bytes(), 1.1))
    dur = lambda p: float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)], capture_output=True, text=True).stdout)
    assert 4.4 < dur(out) < 4.7 and llm.TTS_SPEED == 1.1
