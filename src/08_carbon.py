"""탄소 환산 - 범위로만 제시한다(CLAUDE.md §7).

연 CO2 변화(t) = 추가 승차(회/일) × 365 × 승용차 대체 비율 × 1회 이동거리(km) × 배출계수(kg/차량·km) ÷ 재차인원 ÷ 1000
- 추가 승차: 주 사양 A′의 C1 효과(1년차 점추정과 95% 신뢰구간 상한) × A′ 역의 2023년 일평균 승차.
  서울 전 역(업무·관광형 포함)으로 넓힌 값은 외삽 시나리오로만 붙인다.
- 승용차 대체 비율: 서울시 설문 4%를 중심으로, 25%·100%(전부 승용차에서 왔다는 극단)를 민감도로.
- 계수(emission_factors.csv, 출처는 파일의 source 열): 이동거리는 서울시 교통이용 통계·국가교통DB,
  배출계수는 환경부 온실가스종합정보센터 2021 승인 도로수송 CO2 식(중형 휘발유, g/km = a·차속^(-b))에
  2024년 서울시 차량 통행속도를 넣어 구하고, 재차인원은 국가교통DB 자동차 이용실태조사 값을 쓴다.
  low/central/high 열은 CO2가 낮은/중간/높은 시나리오에 쓰는 값이다(재차인원·차속은 큰 값이 low).
- 서울시 발표(2개월 3,600t = 연 약 21,600t)와 비교한다.
경계 갈래(서사 3): 버스 대체 검정에서 경계 바깥 역 승차 이탈이 주변 서울 버스로 설명되지 않았으므로
'경계 탄소 역효과 가능성'을 조건부로 계산한다 - 이탈 승차의 0/25/50/100%가 승용차로 갔을 때.
서울시 발표 역산: 발표치(하루 2만 명 전환)가 맞으려면 서울 지하철 승차가 몇 % 늘어야 하는지 계산해
1년차 추정·신뢰구간과 비교한다(1인 왕복 2회, 전환 통행 중 지하철 비중 50%·100%).
입력 outputs/tables/cs_Aprime_week_summary.csv, ring_timing_windows.csv,
     data/reference/emission_factors.csv, data/processed/panel_week.parquet
출력 outputs/tables/carbon_factors.csv, carbon_range.csv, carbon_boundary.csv, carbon_seoul_check.csv
"""
from __future__ import annotations

import importlib.util
import sys

import pandas as pd

from common import DATA_PROCESSED, DATA_REFERENCE, OUT_TABLES, ROOT


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "src" / file)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


did = _load("did_cs", "04_did_cs.py")
het = _load("heterogeneity", "06_heterogeneity.py")

CAR_SHARES = {"서울시 설문 4%": 0.04, "25%": 0.25, "100%(극단)": 1.0}
BOUNDARY_CAR_SHARES = {"0%(다른 대중교통)": 0.0, "25%": 0.25, "50%": 0.5, "100%(극단)": 1.0}


def daily_base(stations: list[str]) -> float:
    """역들의 2023년 지하철 일평균 승차 합."""
    p = pd.read_parquet(DATA_PROCESSED / "panel_week.parquet")
    p = p[(p.week >= "2023-01-07") & (p.week < "2024-01-06") & p.complex.isin(stations)]
    return float(p.on.sum() / (p.week.nunique() * 7))


def co2_t_per_year(boardings_per_day: float, car_share: float, f: dict) -> float:
    return boardings_per_day * 365 * car_share * f["trip_km"] * f["car_ef"] / f["occupancy"] / 1000


def scenario_factors(ef: pd.DataFrame) -> dict[str, dict[str, float]]:
    """시나리오별 계수. 배출계수(kg/km) = a·차속^(-b)/1000 (국가 배출계수 식, 65.4km/h 미만 구간)."""
    out = {}
    for lv in ("low", "central", "high"):
        speed = float(ef.at["car_speed_kmh", lv])
        assert speed < 65.4, "65.4km/h 이상은 다른 식(2차식)을 써야 한다"
        a, b = float(ef.at["car_ef_a", lv]), float(ef.at["car_ef_b", lv])
        out[lv] = {"trip_km": float(ef.at["trip_km", lv]), "car_speed_kmh": speed,
                   "car_ef": a * speed ** (-b) / 1000, "occupancy": float(ef.at["occupancy", lv])}
    return out


def main() -> None:
    ef = pd.read_csv(DATA_REFERENCE / "emission_factors.csv").set_index("parameter")
    levels = scenario_factors(ef)
    factors = pd.DataFrame(levels).T.rename_axis("scenario").reset_index()
    factors["co2_kg_per_boarding_at_100pct"] = factors.trip_km * factors.car_ef / factors.occupancy
    factors.to_csv(OUT_TABLES / "carbon_factors.csv", index=False, encoding="utf-8-sig")
    seoul_claim = float(ef.at["seoul_claim_t_per_2months", "central"]) * 6

    s = pd.read_csv(OUT_TABLES / "cs_Aprime_week_summary.csv").set_index("param")
    y1 = s.loc["C1_year1(적용 후 1년차)"]
    units = did.select_units(did.load_long("week", "on"), did.aprime("carbon"))
    a_prime = list(units.index[units.cohort == "C1"])
    cmap = pd.read_csv(DATA_REFERENCE / "cohort_map.csv", dtype=str, keep_default_na=False)
    all_c1 = sorted(set(cmap[(cmap.cohort == "C1") & (cmap.exclude_reason == "")].complex))
    bases = {"A′ 서울 비도심 역(추정 대상)": daily_base(a_prime), "서울 전 역으로 외삽(가정)": daily_base(all_c1)}

    rows = []
    for bname, base in bases.items():
        for ename, eff in (("1년차 점추정", y1.est), ("1년차 95% 상한", y1.hi)):
            extra = base * eff
            for cname, share in CAR_SHARES.items():
                vals = {lv: co2_t_per_year(extra, share, levels[lv]) for lv in levels}
                rows.append({"base": bname, "base_boardings_day": base, "effect": ename, "effect_value": eff,
                             "extra_boardings_day": extra, "car_share": cname,
                             "co2_t_low": vals["low"], "co2_t_central": vals["central"], "co2_t_high": vals["high"],
                             "vs_seoul_claim(연 21,600t)": vals["central"] / seoul_claim})
    rng = pd.DataFrame(rows)
    rng.to_csv(OUT_TABLES / "carbon_range.csv", index=False, encoding="utf-8-sig")

    # 경계 갈래: 1차 링(계양 제외 8역) 이탈 승차가 승용차로 갔다면
    w = pd.read_csv(OUT_TABLES / "ring_timing_windows.csv")
    r1 = w[(w.group == "1차 링") & (w.freq == "week") & (w.window == "노출 후 전체")].iloc[0]
    ring_base = daily_base(het.RING1)
    lost = ring_base * r1.est
    brows = []
    for cname, share in BOUNDARY_CAR_SHARES.items():
        vals = {lv: co2_t_per_year(-lost, share, levels[lv]) for lv in levels}
        brows.append({"ring1_base_boardings_day": ring_base, "effect": r1.est, "effect_se": r1.se,
                      "lost_boardings_day": -lost, "car_share_of_lost": cname,
                      "co2_increase_t_low": vals["low"], "co2_increase_t_central": vals["central"],
                      "co2_increase_t_high": vals["high"]})
    bnd = pd.DataFrame(brows)
    bnd.to_csv(OUT_TABLES / "carbon_boundary.csv", index=False, encoding="utf-8-sig")

    # 서울시 발표 역산: 전환자 × 왕복 2회 × 지하철 비중 → 서울 전 역(C1) 승차 대비 %
    switchers = float(ef.at["seoul_switchers_per_day", "central"])
    base_all = bases["서울 전 역으로 외삽(가정)"]
    chk = pd.DataFrame([{"switchers_per_day": switchers, "subway_share_of_switch_trips": sh,
                         "implied_extra_boardings_day": switchers * 2 * sh, "c1_base_boardings_day": base_all,
                         "implied_effect": switchers * 2 * sh / base_all,
                         "est_year1": y1.est, "lo_year1": y1.lo, "hi_year1": y1.hi,
                         "inside_ci": bool(y1.lo <= switchers * 2 * sh / base_all <= y1.hi)} for sh in (0.5, 1.0)])
    # 추가 승차가 모두 승용차에서 왔다고 할 때(중앙 계수) 서울시 발표치에 닿으려면 필요한 서울 전 역 승차 증가율
    need = seoul_claim / co2_t_per_year(1.0, 1.0, levels["central"])
    chk["claim_needs_boardings_day_at_100pct_car"] = need
    chk["claim_needs_effect_at_100pct_car"] = need / base_all
    chk.to_csv(OUT_TABLES / "carbon_seoul_check.csv", index=False, encoding="utf-8-sig")

    pd.set_option("display.width", 220)
    print("시나리오 계수(배출계수 kg/km는 국가 배출계수 식에 차속을 넣은 값):")
    print(factors.round(4).to_string(index=False))
    print(f"서울시 발표 연환산: {seoul_claim:,.0f} t/년")
    print(rng.round({"base_boardings_day": 0, "effect_value": 4, "extra_boardings_day": 0, "co2_t_low": 0,
                     "co2_t_central": 0, "co2_t_high": 0, "vs_seoul_claim(연 21,600t)": 3}).to_string(index=False))
    print("\n경계 갈래(1차 링 이탈이 승용차로 갔을 때, t/년):")
    print(bnd.round(1).to_string(index=False))
    print("\n서울시 발표 역산(함의하는 승차 증가율 vs 1년차 추정):")
    print(chk.round(4).to_string(index=False))


if __name__ == "__main__":
    main()
