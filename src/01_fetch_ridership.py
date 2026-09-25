"""서울 열린데이터광장 지하철 역별 승하차 원본 수집.

서비스 (데이터셋 OA-12914 계열, 서울교통공사·코레일·공항철도·9호선 포함, 신분당선 미포함)
- CardSubwayStatsNew : 일별 역별 승하차. API는 최근 구간만 보관한다(2026-09-25 점검: 2026-03-01부터).
                       그 이전 일별 자료는 데이터셋 파일 CARD_SUBWAY_MONTH_YYYYMM.csv로 받아
                       data/raw/seoul_daily_csv/ 에 그대로 둔다(수동 또는 별도 다운로드).
- CardSubwayTime     : 월별 × 시간대(04~03시) 역별 승하차. 과거 월 전체 API 제공.

사용 예
  python src/01_fetch_ridership.py probe
  python src/01_fetch_ridership.py hourly --start 202301 --end 202608
  python src/01_fetch_ridership.py daily --start 20260301 --end 20260921
  python src/01_fetch_ridership.py files --start 202301 --end 202608   # 데이터셋 월별 CSV
  python src/01_fetch_ridership.py files --start 2022 --end 2022       # 연도 통합 CSV(4자리)
  python src/01_fetch_ridership.py bus --start 202301 --end 202512     # 버스 노선·정류장별 월×시간대
  python src/01_fetch_ridership.py geo                                 # 역·버스정류장 좌표

버스(CardBusTimeNew, OA-12913)는 서울 면허 버스의 노선×정류장 월 승하차로, 서울 밖 정류장도 들어 있다.
월마다 약 4만 행이라 원본 행을 그대로 parquet로 저장한다(형식만 바꿈, 값·열은 원본 그대로).

원본은 data/raw/ 아래에 받은 그대로 저장하고, 이미 있는 파일은 건너뛴다(--force로 덮어씀).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from collections import Counter

import pandas as pd
import requests

from common import DATA_RAW, OUT_TABLES, load_key, seoul_api, seoul_api_all

DAILY = "CardSubwayStatsNew"
HOURLY = "CardSubwayTime"
BUS = "CardBusTimeNew"
DAILY_DIR = DATA_RAW / "seoul_daily_api"
HOURLY_DIR = DATA_RAW / "seoul_hourly_api"
CSV_DIR = DATA_RAW / "seoul_daily_csv"
BUS_DIR = DATA_RAW / "seoul_bus_hourly_api"
GEO_DIR = DATA_RAW / "seoul_geo_api"
DATASET_PAGE = "https://data.seoul.go.kr/dataList/OA-12914/S/1/datasetView.do"
FILE_DOWNLOAD = "https://datafile.seoul.go.kr/bigfile/iot/inf/nio_download.do?&useCache=false"
BROWSER_UA = {"User-Agent": "Mozilla/5.0"}


def _month_add(ym: str, k: int) -> str:
    y, m = divmod(int(ym[:4]) * 12 + int(ym[4:]) - 1 + k, 12)
    return f"{y:04d}{m + 1:02d}"


def _months(start: str, end: str) -> list[str]:
    out, ym = [], start
    while ym <= end:
        out.append(ym)
        ym = _month_add(ym, 1)
    return out


def _has_daily(d: dt.date, key: str) -> bool:
    return seoul_api(DAILY, 1, 1, f"{d:%Y%m%d}", key=key)[0] > 0


def _has_hourly(ym: str, key: str) -> bool:
    return seoul_api(HOURLY, 1, 1, ym, key=key)[0] > 0


def _save(rows: list[dict], path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")


def probe(key: str) -> None:
    """두 API의 제공 기간(연속 구간 가정, 이분 탐색)과 노선별 역 수를 점검한다."""
    today = dt.date.today()

    latest_day = next(today - dt.timedelta(k) for k in range(15) if _has_daily(today - dt.timedelta(k), key))
    lo, hi = latest_day - dt.timedelta(800), latest_day  # lo: 없음, hi: 있음
    if _has_daily(lo, key):
        raise RuntimeError("일별 API가 800일 이상 보관 — 탐색 범위를 넓힐 것")
    while (hi - lo).days > 1:
        mid = lo + (hi - lo) / 2
        lo, hi = (lo, mid) if _has_daily(mid, key) else (mid, hi)
    earliest_day = hi

    this_month = f"{today:%Y%m}"
    latest_month = next(_month_add(this_month, -k) for k in range(4) if _has_hourly(_month_add(this_month, -k), key))
    months = _months("200801", latest_month)
    if _has_hourly(months[0], key):
        earliest_month = months[0] + " 이전"
    else:
        i_lo, i_hi = 0, len(months) - 1  # months[i_lo]: 없음, months[i_hi]: 있음
        while i_hi - i_lo > 1:
            mid = (i_lo + i_hi) // 2
            i_lo, i_hi = (i_lo, mid) if _has_hourly(months[mid], key) else (mid, i_hi)
        earliest_month = months[i_hi]

    period = pd.DataFrame([
        {"service": DAILY, "unit": "일", "earliest": f"{earliest_day:%Y-%m-%d}",
         "latest": f"{latest_day:%Y-%m-%d}", "checked_on": f"{today:%Y-%m-%d}"},
        {"service": HOURLY, "unit": "월×시간대", "earliest": earliest_month,
         "latest": latest_month, "checked_on": f"{today:%Y-%m-%d}"},
    ])

    # 노선 커버리지 스냅숏: 분석기간 각 1월 + 코호트 개시 월 + 최신 월, 그리고 일별 최신일
    snaps = {ym: seoul_api_all(HOURLY, ym, key=key)
             for ym in ["202301", "202401", "202403", "202408", "202411", "202501", "202505",
                        "202508", "202601", latest_month]}
    snaps[f"일별 {latest_day:%Y%m%d}"] = seoul_api_all(DAILY, f"{latest_day:%Y%m%d}", key=key)
    counts = {
        name: Counter(r["SBWY_ROUT_LN_NM"] for r in rows) for name, rows in snaps.items()
    }
    lines = pd.DataFrame(counts).fillna(0).astype(int).sort_index()
    lines.index.name = "line"

    OUT_TABLES.mkdir(parents=True, exist_ok=True)
    period.to_csv(OUT_TABLES / "api_coverage_period.csv", index=False, encoding="utf-8-sig")
    lines.to_csv(OUT_TABLES / "api_coverage_lines.csv", encoding="utf-8-sig")
    print(period.to_string(index=False))
    print()
    print(lines.to_string())


def fetch_hourly(start: str, end: str, key: str, force: bool) -> None:
    for ym in _months(start, end):
        path = HOURLY_DIR / f"{HOURLY}_{ym}.json"
        if path.exists() and not force:
            continue
        rows = seoul_api_all(HOURLY, ym, key=key)
        if not rows:
            print(f"{ym}: 데이터 없음")
            continue
        _save(rows, path)
        print(f"{ym}: {len(rows)}행")


def fetch_daily(start: str, end: str, key: str, force: bool) -> None:
    d, last = dt.datetime.strptime(start, "%Y%m%d").date(), dt.datetime.strptime(end, "%Y%m%d").date()
    while d <= last:
        path = DAILY_DIR / f"{DAILY}_{d:%Y%m%d}.json"
        if force or not path.exists():
            rows = seoul_api_all(DAILY, f"{d:%Y%m%d}", key=key)
            if rows:
                _save(rows, path)
                print(f"{d}: {len(rows)}행")
            else:
                print(f"{d}: 데이터 없음 (API 보관 기간 밖이면 월별 CSV 파일 사용)")
        d += dt.timedelta(1)


def fetch_files(start: str, end: str, force: bool) -> None:
    """데이터셋 페이지의 파일 목록에서 CARD_SUBWAY_MONTH_{YYYYMM|YYYY}.csv의 seq를 찾아 내려받는다.
    4자리(연도)를 주면 연도 통합 파일(2015~2022 제공)을 받는다."""
    html = requests.get(DATASET_PAGE, headers=BROWSER_UA, timeout=60).text
    seqs = dict(re.findall(
        r'title="(CARD_SUBWAY_MONTH_\d{4}(?:\d{2})?\.csv)" onclick="javascript:downloadFile\(\'(\d+)\'\)', html))
    periods = [str(y) for y in range(int(start), int(end) + 1)] if len(start) == 4 else _months(start, end)
    for ym in periods:
        name = f"CARD_SUBWAY_MONTH_{ym}.csv"
        path = CSV_DIR / name
        if path.exists() and not force:
            continue
        if name not in seqs:
            print(f"{name}: 목록에 없음")
            continue
        form = {"infId": "OA-12914", "seqNo": "", "seq": seqs[name], "infSeq": "3"}
        resp = requests.post(FILE_DOWNLOAD, data=form, headers={**BROWSER_UA, "Referer": DATASET_PAGE}, timeout=120)
        resp.raise_for_status()
        if resp.content[:200].lstrip().lower().startswith((b"<!doctype", b"<html")):
            raise RuntimeError(f"{name}: CSV 대신 HTML 응답")
        CSV_DIR.mkdir(parents=True, exist_ok=True)
        path.write_bytes(resp.content)
        print(f"{name}: {len(resp.content) / 1e6:.2f}MB")


def fetch_bus(start: str, end: str, key: str, force: bool) -> None:
    for ym in _months(start, end):
        path = BUS_DIR / f"{BUS}_{ym}.parquet"
        if path.exists() and not force:
            continue
        rows = seoul_api_all(BUS, ym, key=key)
        if not rows:
            print(f"버스 {ym}: 데이터 없음")
            continue
        BUS_DIR.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_parquet(path, index=False)
        print(f"버스 {ym}: {len(rows)}행", flush=True)


def fetch_geo(key: str) -> None:
    """역 좌표(subwayStationMaster)와 서울 버스정류장 좌표(busStopLocationXyInfo)."""
    GEO_DIR.mkdir(parents=True, exist_ok=True)
    for svc in ("subwayStationMaster", "busStopLocationXyInfo"):
        rows = seoul_api_all(svc, key=key)
        _save(rows, GEO_DIR / f"{svc}.json")
        print(f"{svc}: {len(rows)}행")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("probe", help="API 제공 기간·노선 커버리지 점검")
    sub.add_parser("geo", help="역·버스정류장 좌표")
    for name, fmt in [("hourly", "YYYYMM"), ("daily", "YYYYMMDD"), ("files", "YYYYMM 또는 YYYY"), ("bus", "YYYYMM")]:
        p = sub.add_parser(name)
        p.add_argument("--start", required=True, help=fmt)
        p.add_argument("--end", required=True, help=fmt)
        p.add_argument("--force", action="store_true")
    args = ap.parse_args()

    if args.cmd == "files":
        fetch_files(args.start, args.end, args.force)
        return
    key = load_key("SEOUL_API_KEY")
    if args.cmd == "probe":
        probe(key)
    elif args.cmd == "geo":
        fetch_geo(key)
    elif args.cmd == "hourly":
        fetch_hourly(args.start, args.end, key, args.force)
    elif args.cmd == "bus":
        fetch_bus(args.start, args.end, key, args.force)
    else:
        fetch_daily(args.start, args.end, key, args.force)


if __name__ == "__main__":
    main()
