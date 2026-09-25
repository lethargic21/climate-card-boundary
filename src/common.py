"""공통 설정: 경로, API 키 로딩, 서울 열린데이터광장 호출.

경로에 한글·공백이 있으므로 문자열 결합 대신 pathlib만 쓴다.
API 키는 URL 경로에 들어가므로 예외 메시지에서 반드시 마스킹한다.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

import requests
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
DATA_RAW = ROOT / "data" / "raw"
DATA_PROCESSED = ROOT / "data" / "processed"
DATA_REFERENCE = ROOT / "data" / "reference"
OUT_TABLES = ROOT / "outputs" / "tables"
OUT_FIGURES = ROOT / "outputs" / "figures"

SEOUL_API_BASE = "http://openapi.seoul.go.kr:8088"
SEOUL_PAGE_MAX = 1000  # 서울 OpenAPI 1회 최대 행 수

# 역명 변경(구명 → 현재명). 주석은 데이터상 새 이름이 처음 나온 월.
RENAMES = {
    ("4호선", "당고개"): "불암산",       # 2025-04
    ("7호선", "뚝섬유원지"): "자양",     # 2024-03
    ("경의선", "화전"): "한국항공대",    # 2024-01
    ("경원선", "초성리"): "청산",        # 2023-12 한 달만 초성리
}


def normalize_station(line: str, raw_name: str) -> str:
    """괄호 부기를 떼고 개명을 현재명으로 맞춘다. 예: '청량리(서울시립대입구)' → '청량리'."""
    base = re.sub(r"\(.*\)$", "", raw_name).strip()
    return RENAMES.get((line, base), base)


class SeoulAPIError(RuntimeError):
    pass


def load_key(name: str) -> str:
    """환경변수 → .env 순으로 키를 읽는다. .env에 중복 정의가 있으면 마지막 값이 쓰인다."""
    value = os.environ.get(name) or dotenv_values(ROOT / ".env").get(name)
    if not value:
        raise RuntimeError(f"{name}가 .env에 없습니다.")
    return value.strip()


def seoul_api(service: str, start: int, end: int, *params: str, key: str,
              retries: int = 3, timeout: int = 60) -> tuple[int, list[dict]]:
    """OpenAPI 1회 호출. '데이터 없음'(INFO-200)은 (0, [])로 돌려준다."""
    url = "/".join([SEOUL_API_BASE, key, "json", service, str(start), str(end), *params])
    for attempt in range(retries):
        try:
            resp = requests.get(url, timeout=timeout)
            resp.raise_for_status()
            payload = resp.json()
            break
        except (requests.RequestException, ValueError) as exc:
            if attempt == retries - 1:
                # from None: 체인된 원래 예외에 키가 든 URL이 남지 않게 한다
                raise SeoulAPIError(str(exc).replace(key, "***")) from None
            time.sleep(2 ** attempt)
    body = payload.get(service)
    if body is None:
        result = payload.get("RESULT", {})
        if result.get("CODE") == "INFO-200":
            return 0, []
        raise SeoulAPIError(f"{service} {params}: {result}")
    return int(body["list_total_count"]), body["row"]


def seoul_api_all(service: str, *params: str, key: str) -> list[dict]:
    """페이지를 넘기며 해당 조건의 전 행을 받는다."""
    total, rows = seoul_api(service, 1, SEOUL_PAGE_MAX, *params, key=key)
    start = SEOUL_PAGE_MAX + 1
    while start <= total:
        _, more = seoul_api(service, start, start + SEOUL_PAGE_MAX - 1, *params, key=key)
        rows.extend(more)
        start += SEOUL_PAGE_MAX
    if len(rows) != total:
        raise SeoulAPIError(f"{service} {params}: {len(rows)}행 수신, 기대 {total}행")
    return rows
