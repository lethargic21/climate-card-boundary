"""버스 대체 검정 - 경계 바깥 역에서 빠진 지하철 승차가 서울 면허 버스(기후동행카드 적용)로 옮겨 갔나.

입력
- data/raw/seoul_bus_hourly_api/CardBusTimeNew_YYYYMM.parquet  서울 면허 버스 노선×정류장 월 승차(2023-01~2025-12)
- data/raw/seoul_geo_api/{subwayStationMaster,busStopLocationXyInfo}.json  역·정류장 좌표
- data/processed/panel_week.parquet(지하철), data/reference/cohort_map.csv
역 ↔ 정류장 연결(반경 500m)
- 서울 정류장(좌표 있음): 역 좌표에서 500m 이내
- 서울 밖 정류장(좌표 자료에 없음 - 서울 면허 버스가 서는 경기·인천 정류장): 정류장 이름에 '<역명>역'이
  든 곳(역 앞 정류장의 대용). 다른 역 이름에 걸리는 오탐은 NAME_FALSE_POSITIVE로 뺀다('신중동역' ≠ 중동역)
카드 적용 노선만 센다(서울 광역버스는 기후동행카드 미적용이라 뺀다).
검정
  (1) 도달: 역별 2023년 서울 버스(카드 적용) 일평균 승차 - 닿는 역 / 안 닿는 역
  (2) 지하철 이탈을 닿는 역 vs 안 닿는 역으로 비교(같은 ξ로 차이의 SE) - 기제의 직접 검정
  (3) 경계 바깥 역 주변 서울 버스 승차가 서울 안쪽 역(A′ C1) 주변보다 더 늘었나(전년 동기 대비)
  (4) 물량 대조: 지하철에서 빠진 승차(명/일) vs 주변 서울 버스에서 늘어난 승차(명/일)
출력 outputs/tables/bus_reach.csv, bus_subway_by_reach.csv, bus_growth.csv, bus_volume.csv
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys

import numpy as np
import pandas as pd

from common import DATA_RAW, OUT_TABLES, ROOT


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "src" / file)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


did = _load("did_cs", "04_did_cs.py")
het = _load("heterogeneity", "06_heterogeneity.py")

RADIUS_M = 500
REACH_MIN_DAILY = 100  # 2023년 주변 서울 버스(카드 적용) 일평균 승차가 이 이상이면 '닿는 역'
NOT_CARD = {"서울광역버스"}
HOMONYM = {("양평", "5호선"): "양평(5호선)", ("양평", "중앙선"): "양평(중앙선)", ("양평", "경의중앙선"): "양평(중앙선)",
           ("신촌", "2호선"): "신촌(2호선)", ("신촌", "경의중앙선"): "신촌(경의선)"}
SAME = {"총신대입구": "이수"}
B_IN = ["도봉산", "신내", "금천구청", "온수", "복정", "남태령", "수색", "강일", "불암산"]
NAME_FALSE_POSITIVE = {"중동": ("신중동역",)}  # 전체 매칭을 눈으로 확인해 찾은 오탐


def station_coords() -> pd.DataFrame:
    st = pd.DataFrame(json.loads((DATA_RAW / "seoul_geo_api" / "subwayStationMaster.json").read_text(encoding="utf-8")))
    name = st.BLDN_NM.str.replace(r"\(.*\)$", "", regex=True).str.strip()
    st["complex"] = [HOMONYM.get((n, r), SAME.get(n, n)) for n, r in zip(name, st.ROUTE)]
    st[["lat", "lon"]] = st[["LAT", "LOT"]].astype(float)
    return st.groupby("complex")[["lat", "lon"]].mean()


def bus_monthly() -> pd.DataFrame:
    """정류장 × 월 카드 적용 노선 승차."""
    frames = []
    for path in sorted((DATA_RAW / "seoul_bus_hourly_api").glob("CardBusTimeNew_*.parquet")):
        b = pd.read_parquet(path)
        b = b[~b.TRFC_MNS_TYPE_NM.isin(NOT_CARD)]
        on_cols = [c for c in b.columns if "GET_ON" in c]
        b["on"] = b[on_cols].astype(float).sum(axis=1)
        frames.append(b.groupby(["USE_YM", "STOPS_ID"]).agg(on=("on", "sum"), name=("SBWY_STNS_NM", "first"),
                                                            routes=("RTE_NO", lambda s: ",".join(sorted(set(s)))))
                      .reset_index())
    out = pd.concat(frames, ignore_index=True)
    out["month"] = pd.to_datetime(out.USE_YM, format="%Y%m")
    out["name"] = out.name.str.replace(r"\(\d+\)$", "", regex=True)
    return out


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6_371_000
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp, dl = p2 - p1, np.radians(lon2 - lon1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def link_stops(targets: list[str], coords: pd.DataFrame, bus: pd.DataFrame) -> pd.DataFrame:
    """역 → 연결 정류장(반경 500m 좌표 판정 또는 서울 밖 정류장 이름 판정)."""
    xy = pd.DataFrame(json.loads((DATA_RAW / "seoul_geo_api" / "busStopLocationXyInfo.json").read_text(encoding="utf-8")))
    xy = xy[xy.STOPS_TYPE != "한강선착장"].assign(lat=lambda d: d.YCRD.astype(float), lon=lambda d: d.XCRD.astype(float))
    names = bus.drop_duplicates("STOPS_ID").set_index("STOPS_ID").name
    no_xy = names[~names.index.isin(xy.STOPS_NO)]
    rows = []
    for s in targets:
        if s in coords.index:
            d = haversine_m(coords.at[s, "lat"], coords.at[s, "lon"], xy.lat.to_numpy(), xy.lon.to_numpy())
            rows += [{"complex": s, "STOPS_ID": i, "method": "좌표 500m"} for i in xy.STOPS_NO[d <= RADIUS_M]]
        base = re.sub(r"\(.*\)$", "", s)
        bad = NAME_FALSE_POSITIVE.get(base, ())
        rows += [{"complex": s, "STOPS_ID": i, "method": "이름(서울 밖)"} for i, n in no_xy.items()
                 if f"{base}역" in n and not any(x in n for x in bad)]
    return pd.DataFrame(rows).drop_duplicates(["complex", "STOPS_ID"])


def area_panel(links: pd.DataFrame, bus: pd.DataFrame) -> pd.DataFrame:
    """역 주변(연결 정류장 합) × 월 서울 버스 승차."""
    m = links.merge(bus, on="STOPS_ID")
    out = m.groupby(["complex", "month"]).on.sum().reset_index()
    out["days"] = out.month.dt.days_in_month
    return out


def subway_baseline() -> pd.Series:
    """역별 2023년 지하철 일평균 승차."""
    p = pd.read_parquet(ROOT / "data" / "processed" / "panel_week.parquet")
    p = p[(p.week >= "2023-01-07") & (p.week < "2024-01-06")]
    return p.groupby("complex").on.sum() / (p.groupby("complex").week.nunique() * 7)


def main() -> None:
    pd.set_option("display.width", 220)
    coords = station_coords()
    bus = bus_monthly()
    cmap = pd.read_csv(ROOT / "data" / "reference" / "cohort_map.csv", dtype=str, keep_default_na=False)
    main_c1 = sorted(set(cmap[(cmap.cohort == "C1") & (cmap.exclude_reason == "")].complex))
    ring1, ring2 = het.RING1_ALL, het.RING2
    targets = sorted(set(ring1 + ring2 + B_IN + main_c1))
    missing = [s for s in ring1 + ring2 + B_IN if s not in coords.index]
    links = link_stops(targets, coords, bus)
    area = area_panel(links, bus)

    # (1) 도달
    y23 = area[area.month.dt.year == 2023].groupby("complex").agg(on=("on", "sum"), days=("days", "sum"))
    daily23 = (y23.on / y23.days).rename("bus_daily_2023")
    routes = links.merge(bus.drop_duplicates("STOPS_ID")[["STOPS_ID", "routes"]], on="STOPS_ID") \
        .groupby("complex").routes.agg(lambda s: ",".join(sorted({r for x in s for r in x.split(",")})))
    reach = pd.DataFrame({"group": ["1차 링"] * len(ring1) + ["2차 링"] * len(ring2) + ["서울 쪽 경계역"] * len(B_IN)},
                         index=ring1 + ring2 + B_IN)
    reach = reach.join(links.groupby("complex").STOPS_ID.nunique().rename("n_stops")).join(daily23).join(routes)
    reach = reach.fillna({"n_stops": 0, "bus_daily_2023": 0.0, "routes": ""})
    reach["subway_daily_2023"] = subway_baseline().reindex(reach.index)
    reach["닿음"] = reach.bus_daily_2023 >= REACH_MIN_DAILY
    reach.index.name = "complex"
    reach.to_csv(OUT_TABLES / "bus_reach.csv", encoding="utf-8-sig")
    print(f"좌표 못 찾은 역: {missing}")
    print("=== (1) 서울 버스 도달 ===")
    print(reach.round(0).to_string())

    # (2) 지하철 이탈을 닿는 역 vs 안 닿는 역으로 - 계양은 사전추세·검단연장 교란으로 제외
    groups = {}
    for gname, members in (("1차 링", het.RING1), ("2차 링", ring2)):
        r = reach.loc[members]
        groups[f"{gname}·닿음"] = list(r.index[r.닿음])
        groups[f"{gname}·안 닿음"] = list(r.index[~r.닿음])
    groups = {k: v for k, v in groups.items() if v}
    cache: dict = {}
    fits, lab = het.joint_fits(groups, het.C1_DATE, "week", cache)
    rows, draws = [], {}
    for name, (cells, agg, n) in fits.items():
        post = (cells.e >= 0).to_numpy()
        est, se, d = agg.estimate(post)
        pre_est, pre_se, _ = agg.estimate(~post)
        rows.append({"group": name, "stations": ",".join(groups[name]), "n": n, "est": est, "se": se,
                     "pre_placebo": pre_est, "pre_se": pre_se})
        draws[name] = est + d
    for g in ("1차 링", "2차 링"):
        a, b = f"{g}·닿음", f"{g}·안 닿음"
        if a in draws and b in draws:
            diff = draws[a] - draws[b]
            rows.append({"group": f"{g}: 닿음 − 안 닿음", "est": float(np.mean(diff)), "se": float(diff.std(ddof=1))})
    by_reach = pd.DataFrame(rows)
    by_reach.to_csv(OUT_TABLES / "bus_subway_by_reach.csv", index=False, encoding="utf-8-sig")
    print("\n=== (2) 지하철 승차 변화: 서울 버스가 닿는 역 vs 안 닿는 역 (%) ===")
    show = by_reach.copy()
    for c in ["est", "se", "pre_placebo", "pre_se"]:
        show[c] = (100 * show[c]).round(2)
    print(show.to_string(index=False))

    # (3) 역 주변 서울 버스 승차: 경계 바깥(닿는 역) vs 서울 안쪽 A′ C1 역 주변 - 전년 동기 대비
    reached = [s for s in het.RING1 + ring2 if reach.at[s, "닿음"]]
    growth_rows = []
    for gname, members in (("1차 링(닿는 역)", [s for s in het.RING1 if s in reached]),
                           ("2차 링(닿는 역)", [s for s in ring2 if s in reached]),
                           ("서울 쪽 경계역", B_IN)):
        u = pd.DataFrame(index=pd.Index(members + main_c1, name="complex"))
        u["cohort"] = ["B"] * len(members) + ["NT"] * len(main_c1)
        u["treat_date"] = [het.C1_DATE] * len(members) + [pd.NaT] * len(main_c1)
        u["stratum"] = "ALL"
        u = u[~u.index.duplicated()]
        p = area[area.complex.isin(u.index)].assign(period=lambda d: d.month,
                                                  y=lambda d: np.log((d.on / d.days).where(d.on > 0)))
        u = u.loc[u.index.intersection(p.complex.unique())]
        wide, G, labels = did.build_wide(p, u, "month")
        cells, contrib = did.att_gt(wide, G, "seasonal", "never", 12)
        agg = did.Aggregator(cells, contrib)
        post = (cells.e >= 0).to_numpy()
        t = pd.DatetimeIndex(labels.reindex(cells.t).to_numpy())
        for wname, mask in (("적용 후 전체", post), ("2024", post & (t.year == 2024)), ("2025", post & (t.year == 2025))):
            est, se, _ = agg.estimate(mask)
            growth_rows.append({"group": gname, "window": wname, "n": int((G == G.max()).sum()),
                                "est": est, "se": se})
    growth = pd.DataFrame(growth_rows)
    growth.to_csv(OUT_TABLES / "bus_growth.csv", index=False, encoding="utf-8-sig")
    print("\n=== (3) 역 주변 서울 버스 승차 변화 - 서울 안쪽 A′ 역 주변 대비, 전년 동기 대비 (%) ===")
    print(growth.assign(est=(100 * growth.est).round(2), se=(100 * growth.se).round(2)).to_string(index=False))

    # (4) 물량 대조: 1차 링 닿는 역
    ring1_fit = {name: fits[name] for name in fits if name == "1차 링·닿음"}
    vol = []
    if ring1_fit:
        cells, agg, _ = ring1_fit["1차 링·닿음"]
        sub_eff = agg.estimate((cells.e >= 0).to_numpy())[0]
        g1 = growth[(growth.group == "1차 링(닿는 역)") & (growth.window == "적용 후 전체")].est.iloc[0]
        members = groups["1차 링·닿음"]
        sub_base = reach.loc[members, "subway_daily_2023"].sum()
        bus_base = reach.loc[members, "bus_daily_2023"].sum()
        vol.append({"stations": ",".join(members), "subway_daily_2023": sub_base, "subway_effect": sub_eff,
                    "subway_change_per_day": sub_base * (np.exp(sub_eff) - 1),
                    "bus_daily_2023": bus_base, "bus_extra_growth": g1,
                    "bus_change_per_day(서울 안쪽 대비 추가분)": bus_base * (np.exp(g1) - 1)})
    volume = pd.DataFrame(vol)
    volume.to_csv(OUT_TABLES / "bus_volume.csv", index=False, encoding="utf-8-sig")
    print("\n=== (4) 물량 대조 (1차 링 닿는 역, 명/일) ===")
    print(volume.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
