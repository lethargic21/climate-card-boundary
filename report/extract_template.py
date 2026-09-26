"""주최측 분석보고서 양식(HWP 5.0)에서 본문 텍스트와 로고 그림을 뽑는다.

HWP 5.0은 OLE 복합 파일이다. FileHeader의 속성 비트 0이 켜져 있으면 BodyText·BinData 스트림이
raw deflate(zlib wbits=-15)로 압축되어 있다. BodyText/Section0은 레코드(태그 10비트·레벨 10비트·크기 12비트)의
나열이고, 문단 글자는 HWPTAG_PARA_TEXT(67) 레코드에 UTF-16LE로 들어 있다(0~31은 제어 문자).

실행: python report/extract_template.py [양식.hwp]   (기본: report/붙임2-분석보고서최종.hwp)
출력: report/assets/template_section0.txt(문단별 텍스트), report/assets/BIN0001.png·BIN0002.png 등 BinData 그림
양식 원본(.hwp)은 저장소에 올리지 않는다(.gitignore).
"""
from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

import olefile

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"
HWPTAG_PARA_TEXT = 67
CHAR_CONTROLS = {0, 10, 13, 24, 25, 26, 27, 28, 29, 30, 31}  # 1 WCHAR짜리 제어 문자(나머지 0~31은 8 WCHAR)


def read_stream(ole: olefile.OleFileIO, name: str, compressed: bool) -> bytes:
    data = ole.openstream(name).read()
    if compressed:
        try:
            return zlib.decompress(data, -15)
        except zlib.error:
            return data  # 일부 BinData는 압축하지 않고 저장된다
    return data


def para_text(payload: bytes) -> str:
    chars = struct.unpack(f"<{len(payload) // 2}H", payload[: len(payload) // 2 * 2])
    out, i = [], 0
    while i < len(chars):
        c = chars[i]
        if c < 32:
            if c in (10, 13):
                out.append("\n")
            i += 1 if c in CHAR_CONTROLS else 8
            continue
        out.append(chr(c))
        i += 1
    return "".join(out).strip("\n")


def records(data: bytes):
    pos = 0
    while pos + 4 <= len(data):
        header = struct.unpack_from("<I", data, pos)[0]
        tag, level, size = header & 0x3FF, (header >> 10) & 0x3FF, (header >> 20) & 0xFFF
        pos += 4
        if size == 0xFFF:
            size = struct.unpack_from("<I", data, pos)[0]
            pos += 4
        yield tag, level, data[pos:pos + size]
        pos += size


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "붙임2-분석보고서최종.hwp"
    ole = olefile.OleFileIO(str(src))
    header = ole.openstream("FileHeader").read()
    if not header.startswith(b"HWP Document File"):
        raise ValueError("HWP 5.0 문서가 아니다")
    compressed = bool(struct.unpack_from("<I", header, 36)[0] & 1)
    ASSETS.mkdir(exist_ok=True)

    body = read_stream(ole, "BodyText/Section0", compressed)
    paras = [(lv, para_text(p)) for tag, lv, p in records(body) if tag == HWPTAG_PARA_TEXT]
    lines = [f"{lv:2d} | {t}" for lv, t in paras if t.strip()]
    (ASSETS / "template_section0.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"문단 {len(lines)}개 → {ASSETS / 'template_section0.txt'}")

    for entry in ole.listdir():
        if entry[0] == "BinData":
            name = entry[-1]
            data = read_stream(ole, "/".join(entry), compressed)
            (ASSETS / name).write_bytes(data)
            is_png = data[:8] == bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])
            print(f"그림 {name}: {len(data):,} bytes, PNG 서명 {'있음' if is_png else '없음'}")


if __name__ == "__main__":
    main()
