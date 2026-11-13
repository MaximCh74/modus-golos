#!/usr/bin/env python3
"""ZIP с шифрованием AES-256 (формат WinZip AE-2) — открывается 7-Zip, WinRAR, Keka, The Unarchiver, PeaZip.
Обычный `zip -e` шифрует старым ZipCrypto (вскрывается), поэтому архив для проверки собираем сами: PBKDF2-HMAC-SHA1 (1000 итераций,
соль 16 байт) → ключ AES-256 в режиме CTR (счётчик little-endian с единицы) + HMAC-SHA1 (10 байт) над шифртекстом; сжатие — deflate.
После записи архив проверяется: каждый файл расшифровывается, сверяется код подлинности и содержимое.

Пароль — со стандартного ввода (его передаёт tools/make_review_archive.sh), в аргументах и файлах его нет.
Запуск: printf '%s' "$PW" | python3 tools/aes_zip.py <архив.zip> <папка>"""
from __future__ import annotations

import getpass
import hashlib
import hmac
import os
import struct
import sys
import time
import zipfile
import zlib
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

SALT, KEY, CHUNK = 16, 32, 1 << 20


def _keys(password: bytes, salt: bytes) -> tuple[bytes, bytes, bytes]:
    dk = hashlib.pbkdf2_hmac("sha1", password, salt, 1000, 2 * KEY + 2)
    return dk[:KEY], dk[KEY:2 * KEY], dk[2 * KEY:]


def _ctr(key: bytes, data: bytes) -> bytes:
    """AES-CTR по WinZip: блок счётчика — номер блока little-endian, начиная с 1."""
    enc = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    out = bytearray()
    block = 1
    for off in range(0, len(data), CHUNK):
        part = data[off:off + CHUNK]
        n = (len(part) + 15) // 16
        stream = enc.update(b"".join((block + i).to_bytes(16, "little") for i in range(n)))[:len(part)]
        out += (int.from_bytes(part, "little") ^ int.from_bytes(stream, "little")).to_bytes(len(part), "little")
        block += n
    return bytes(out)


def _dos_time(ts: float) -> tuple[int, int]:
    t = time.localtime(ts)
    return (t.tm_hour << 11) | (t.tm_min << 5) | (t.tm_sec // 2), ((max(t.tm_year, 1980) - 1980) << 9) | (t.tm_mon << 5) | t.tm_mday


def write(zip_path: Path, root: Path, password: bytes) -> list[tuple[str, Path]]:
    files = sorted(p for p in root.rglob("*") if p.is_file() and not p.is_symlink())
    extra = struct.pack("<HHH2sBH", 0x9901, 7, 2, b"AE", 3, 8)   # AE-2, AES-256, внутри deflate
    central, entries = [], []
    with open(zip_path, "wb") as f:
        for p in files:
            name = p.relative_to(root.parent).as_posix().encode("utf-8")
            data = p.read_bytes()
            comp = zlib.compressobj(6, zlib.DEFLATED, -15)
            packed = comp.compress(data) + comp.flush()
            salt = os.urandom(SALT)
            aes_key, mac_key, check = _keys(password, salt)
            ct = _ctr(aes_key, packed)
            mac = hmac.new(mac_key, ct, hashlib.sha1).digest()[:10]
            payload = salt + check + ct + mac
            mtime, mdate = _dos_time(p.stat().st_mtime)
            offset = f.tell()
            flags = 0x0001 | 0x0800   # зашифровано, имена в UTF-8
            f.write(struct.pack("<IHHHHHIIIHH", 0x04034B50, 51, flags, 99, mtime, mdate, 0, len(payload), len(data), len(name), len(extra)))
            f.write(name + extra + payload)
            central.append(struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, (3 << 8) | 51, 51, flags, 99, mtime, mdate, 0, len(payload), len(data),
                                       len(name), len(extra), 0, 0, 0, (0o100644 << 16), offset) + name + extra)
            entries.append((name.decode("utf-8"), p))
        cd_start = f.tell()
        for c in central:
            f.write(c)
        cd_size = f.tell() - cd_start
        f.write(struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, len(central), len(central), cd_size, cd_start, 0))
    return entries


def verify(zip_path: Path, entries: list[tuple[str, Path]], password: bytes) -> None:
    """Расшифровать каждый файл, сверить код подлинности и содержимое с исходником."""
    with zipfile.ZipFile(zip_path) as z, open(zip_path, "rb") as f:
        infos = {i.filename: i for i in z.infolist()}
        for name, src in entries:
            i = infos[name]
            f.seek(i.header_offset)
            head = f.read(30)
            n, e = struct.unpack("<HH", head[26:30])
            f.seek(i.header_offset + 30 + n + e)
            payload = f.read(i.compress_size)
            salt, check, ct, mac = payload[:SALT], payload[SALT:SALT + 2], payload[SALT + 2:-10], payload[-10:]
            aes_key, mac_key, check2 = _keys(password, salt)
            if check != check2 or not hmac.compare_digest(mac, hmac.new(mac_key, ct, hashlib.sha1).digest()[:10]):
                raise SystemExit(f"проверка не прошла: {name}")
            if zlib.decompress(_ctr(aes_key, ct), -15) != src.read_bytes():
                raise SystemExit(f"содержимое не совпало: {name}")


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    zip_path, root = Path(sys.argv[1]), Path(sys.argv[2])
    password = (getpass.getpass("Пароль: ") if sys.stdin.isatty() else sys.stdin.read()).encode("utf-8")
    if len(password) < 8:
        raise SystemExit("пароль короче 8 символов")
    entries = write(zip_path, root, password)
    verify(zip_path, entries, password)
    print(f"архив: {zip_path} — файлов {len(entries)}, {zip_path.stat().st_size / 1e6:.1f} МБ, AES-256, проверен")


if __name__ == "__main__":
    main()
