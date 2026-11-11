"""Каждому тестовому модулю — своя чистая база и папка данных: тесты не влияют друг на друга."""
import os
import tempfile

import pytest

os.environ.setdefault("MF_STT", "off")
os.environ.setdefault("MF_STT_WARMUP", "0")


@pytest.fixture(scope="module", autouse=True)
def fresh_data_dir():
    from mf import db
    db.use(tempfile.mkdtemp(prefix="mf-test-"))
    os.environ.pop("OPENAI_API_KEY", None)   # тесты идут без живого ключа (mf.config подтягивает .env при импорте)
    yield
