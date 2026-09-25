"""역(복합역) × 주·월 패널 생성.

입력
- data/raw/seoul_daily_csv/CARD_SUBWAY_MONTH_YYYYMM.csv  일별 (2023-01~2026-08, 데이터셋 파일)
- data/raw/seoul_daily_api/*.json                         일별 (파일 마지막 날 이후분, 겹치는 날은 대조 검증)
- data/raw/seoul_hourly_api/*.json                        월×시간대 (2022-01~)
- data/reference/cohort_map.csv
출력
- data/processed/panel_week.parquet   complex × 주(토~금): on, off, on_work/n_work(평일), on_rest/n_rest(휴일),
                                      holiday_week + 코호트 정보
- data/processed/panel_month.parquet  complex × 월: on, on_peak(07~09시·18~20시), on_offpeak + 코호트 정보
- data/processed/station_profile_2023.parquet  complex별 2023년(사전기간) 시간대별 승차 비중 — 역 유형 분류용

규칙
- 주는 토요일 시작(처리일 6개가 모두 토요일). 7일이 모두 있는 주만 남긴다.
- 역명 정규화는 common.normalize_station, 복합역·코호트·제외 사유는 cohort_map.csv를 따른다.
- data_artifact 행은 합산하지 않는다. 월×시간대 원본의 중복 적재 행(2026-03·07)은 제거한다.
- holiday_week: 설·추석 연휴가 낀 주 — 추정에서 뺀다.
- 평일 = 공휴일이 아닌 월~금, 휴일 = 토·일·공휴일(PUBLIC_HOLIDAYS).
"""
from __future__ import annotations

import json

import pandas as pd

from common import DATA_PROCESSED, DATA_RAW, DATA_REFERENCE, normalize_station

BOM = bytes([0xEF, 0xBB, 0xBF])
# 설·추석 연휴(대체·임시공휴일 포함) — 지식 기반, STATUS.md 가정 참조
MAJOR_HOLIDAYS = [
    ("2022-01-31", "2022-02-02"), ("2022-09-09", "2022-09-12"),
    ("2023-01-21", "2023-01-24"), ("2023-09-28", "2023-10-03"),
    ("2024-02-09", "2024-02-12"), ("2024-09-16", "2024-09-18"),
    ("2025-01-25", "2025-01-30"), ("2025-10-03", "2025-10-09"),
    ("2026-02-14", "2026-02-18"), ("2026-09-24", "2026-09-26"),
]
# 관공서 공휴일(대체·임시공휴일·선거일 포함) — 지식 기반, STATUS.md 가정 참조. 평일/휴일 구분용
PUBLIC_HOLIDAYS = pd.to_datetime([
    "2023-01-01", "2023-01-21", "2023-01-22", "2023-01-23", "2023-01-24", "2023-03-01", "2023-05-05",
    "2023-05-27", "2023-05-29", "2023-06-06", "2023-08-15", "2023-09-28", "2023-09-29", "2023-09-30",
    "2023-10-02", "2023-10-03", "2023-10-09", "2023-12-25",
    "2024-01-01", "2024-02-09", "2024-02-10", "2024-02-11", "2024-02-12", "2024-03-01", "2024-04-10",
    "2024-05-05", "2024-05-06", "2024-05-15", "2024-06-06", "2024-08-15", "2024-09-16", "2024-09-17",
    "2024-09-18", "2024-10-01", "2024-10-03", "2024-10-09", "2024-12-25",
    "2025-01-01", "2025-01-27", "2025-01-28", "2025-01-29", "2025-01-30", "2025-03-01", "2025-03-03",
    "2025-05-05", "2025-05-06", "2025-06-03", "2025-06-06", "2025-08-15", "2025-10-03", "2025-10-05",
    "2025-10-06", "2025-10-07", "2025-10-08", "2025-10-09", "2025-12-25",
    "2026-01-01", "2026-02-16", "2026-02-17", "2026-02-18", "2026-03-01", "2026-03-02", "2026-05-05",
    "2026-05-24", "2026-05-25", "2026-06-03", "2026-06-06", "2026-08-15", "2026-08-17",
    "2026-09-24", "2026-09-25", "2026-09-26",
])
PEAK_HOURS = (7, 8, 18, 19)  # 07~09시, 18~20시 승차


def read_daily_csv() -> pd.DataFrame:
    frames = []
    for path in sorted((DATA_RAW / "seoul_daily_csv").glob("CARD_SUBWAY_MONTH_*.csv")):
        # 대부분 UTF-8(BOM)·따옴표 형식이지만 2024-02·2025-02는 CP949·따옴표 없음
        enc = "utf-8-sig" if path.read_bytes()[:3] == BOM else "cp949"
        # 헤더는 6칸, 데이터 행은 끝에 빈 칸이 하나 더 붙어 7칸 — 앞 6칸만 읽는다
        df = pd.read_csv(path, encoding=enc, dtype=str, usecols=range(6))
        df.columns = ["date", "line", "station_raw", "on", "off", "reg"]
        frames.append(df.drop(columns="reg"))
    return pd.concat(frames, ignore_index=True)


def read_daily_api() -> pd.DataFrame:
    rows = [r for p in sorted((DATA_RAW / "seoul_daily_api").glob("*.json"))
            for r in json.loads(p.read_text(encoding="utf-8"))]
    df = pd.DataFrame(rows)[["USE_YMD", "SBWY_ROUT_LN_NM", "SBWY_STNS_NM", "GTON_TNOPE", "GTOFF_TNOPE"]]
    df.columns = ["date", "line", "station_raw", "on", "off"]
    return df


def load_daily() -> pd.DataFrame:
    csv, api = read_daily_csv(), read_daily_api()
    last_csv = csv.date.max()
    overlap = csv.merge(api, on=["date", "line", "station_raw"], suffixes=("", "_api"))
    if not overlap.empty:
        diff = (overlap.on.astype(int) != overlap.on_api.astype(int)).sum()
        print(f"파일·API 겹치는 날 {overlap.date.nunique()}일 {len(overlap)}행 중 승차 불일치 {diff}행")
    df = pd.concat([csv, api[api.date > last_csv]], ignore_index=True)
    df["date"] = pd.to_datetime(df.date, format="%Y%m%d")
    df[["on", "off"]] = df[["on", "off"]].astype(int)
    df["station"] = [normalize_station(ln, s) for ln, s in zip(df.line, df.station_raw)]
    return df


def complex_info(cmap: pd.DataFrame) -> pd.DataFrame:
    """복합역 단위 코호트·처리일·제외 사유 (data_artifact 행 제외)."""
    real = cmap[(cmap.in_data == "Y") & ~cmap.exclude_reason.str.contains("data_artifact")]
    info = real.groupby("complex").agg(
        cohort=("cohort", lambda s: s.iloc[0] if s.nunique() == 1 else "MIXED"),
        treat_date=("treat_date", "first"),
        exclude_reason=("exclude_reason", lambda s: ";".join(sorted({c for v in s for c in v.split(";") if c}))),
        sido=("sido", "first"), sigungu=("sigungu", "first"))
    info["treat_date"] = pd.to_datetime(info.treat_date.where(info.treat_date != ""))
    return info


def attach(panel: pd.DataFrame, cmap: pd.DataFrame, raw_keys: pd.DataFrame) -> pd.DataFrame:
    unmatched = raw_keys.merge(cmap[["line", "station"]], how="left", indicator=True)
    unmatched = unmatched[unmatched._merge == "left_only"]
    if len(unmatched):
        raise RuntimeError(f"cohort_map에 없는 (노선, 역): {unmatched[['line', 'station']].values.tolist()}")
    return panel.join(complex_info(cmap), on="complex")


def build_week(daily: pd.DataFrame, cmap: pd.DataFrame) -> pd.DataFrame:
    keys = cmap.loc[cmap.in_data == "Y", ["line", "station", "complex", "exclude_reason"]]
    df = daily.merge(keys, on=["line", "station"], how="left")
    df = df[~df.exclude_reason.fillna("").str.contains("data_artifact")]
    per_day = df.groupby(["complex", "date"])[["on", "off"]].sum().reset_index()
    # 토요일(weekday 5) 시작 주
    per_day["week"] = per_day.date - pd.to_timedelta((per_day.date.dt.weekday - 5) % 7, unit="D")
    rest = (per_day.date.dt.weekday >= 5) | per_day.date.isin(PUBLIC_HOLIDAYS)
    per_day["on_work"], per_day["on_rest"] = per_day.on.where(~rest, 0), per_day.on.where(rest, 0)
    per_day["n_work"], per_day["n_rest"] = (~rest).astype(int), rest.astype(int)
    week = per_day.groupby(["complex", "week"]).agg(
        on=("on", "sum"), off=("off", "sum"), n_days=("date", "nunique"),
        on_work=("on_work", "sum"), n_work=("n_work", "sum"),
        on_rest=("on_rest", "sum"), n_rest=("n_rest", "sum")).reset_index()
    week = week[week.n_days == 7].drop(columns="n_days")
    hol = pd.concat([pd.Series(pd.date_range(a, b)) for a, b in MAJOR_HOLIDAYS])
    hol_weeks = set(hol - pd.to_timedelta((hol.dt.weekday - 5) % 7, unit="D"))
    week["holiday_week"] = week.week.isin(hol_weeks)
    return attach(week, cmap, daily[["line", "station"]].drop_duplicates())


def load_hourly(cmap: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    frames = [pd.DataFrame(json.loads(p.read_text(encoding="utf-8")))
              for p in sorted((DATA_RAW / "seoul_hourly_api").glob("CardSubwayTime_*.json"))]
    raw = pd.concat(frames).drop_duplicates()
    on_cols = [c for c in raw.columns if c.endswith("_GET_ON_NOPE")]
    raw[on_cols] = raw[on_cols].apply(pd.to_numeric)
    raw["on"] = raw[on_cols].sum(axis=1)
    raw["line"] = raw.SBWY_ROUT_LN_NM
    raw["station"] = [normalize_station(ln, s) for ln, s in zip(raw.line, raw.STTN)]
    keys = cmap.loc[cmap.in_data == "Y", ["line", "station", "complex", "exclude_reason"]]
    df = raw.merge(keys, on=["line", "station"], how="left")
    return df[~df.exclude_reason.fillna("").str.contains("data_artifact")], on_cols


def build_profile(hourly: pd.DataFrame, on_cols: list[str]) -> pd.DataFrame:
    """2023년 시간대별 승차 비중(HR_4 … HR_3). 사전기간 값이라 처리 결과에 오염되지 않는다."""
    y2023 = hourly[hourly.USE_MM.str.startswith("2023")].groupby("complex")[on_cols].sum()
    share = y2023.div(y2023.sum(axis=1), axis=0)
    share.columns = [c.replace("_GET_ON_NOPE", "").replace("HR_", "h") for c in share.columns]
    share["on_2023"] = y2023.sum(axis=1)
    return share.reset_index()


def build_month(hourly: pd.DataFrame, cmap: pd.DataFrame) -> pd.DataFrame:
    # cohort_map(2023~ 기준)에 없는 과거 역명은 complex가 비어 groupby에서 빠진다
    hourly = hourly.assign(on_peak=hourly[[f"HR_{h}_GET_ON_NOPE" for h in PEAK_HOURS]].sum(axis=1))
    month = hourly.groupby(["complex", "USE_MM"])[["on", "on_peak"]].sum().reset_index()
    month["on_offpeak"] = month.on - month.on_peak
    month["month"] = pd.to_datetime(month.USE_MM, format="%Y%m")
    month["days"] = month.month.dt.days_in_month
    month = month.drop(columns="USE_MM")
    return month.join(complex_info(cmap), on="complex")


def main() -> None:
    cmap = pd.read_csv(DATA_REFERENCE / "cohort_map.csv", dtype=str, keep_default_na=False)
    daily = load_daily()
    week = build_week(daily, cmap)
    hourly, on_cols = load_hourly(cmap)
    month = build_month(hourly, cmap)
    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    week.to_parquet(DATA_PROCESSED / "panel_week.parquet", index=False)
    month.to_parquet(DATA_PROCESSED / "panel_month.parquet", index=False)
    build_profile(hourly, on_cols).to_parquet(DATA_PROCESSED / "station_profile_2023.parquet", index=False)
    print(f"주 패널: {week.complex.nunique()}개 역 × {week.week.nunique()}주 "
          f"({week.week.min():%Y-%m-%d} ~ {week.week.max():%Y-%m-%d}), 명절 주 {week[week.holiday_week].week.nunique()}개")
    print(f"월 패널: {month.complex.nunique()}개 역 × {month.month.nunique()}개월 "
          f"({month.month.min():%Y-%m} ~ {month.month.max():%Y-%m})")


if __name__ == "__main__":
    main()
