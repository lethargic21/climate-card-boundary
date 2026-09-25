"""처리군 내부 이질성(서사 2)과 경계 흡수(서사 3). 추정은 04_did_cs.py의 CS-DiD를 그대로 쓴다.

서사 2 — 무제한 정기권이 늘린 통행은 어느 시간·요일에 있나 (주 사양 A′ 조건):
  평일/휴일  주 패널: 공휴일 아닌 월~금 일평균 vs 토·일·공휴일 일평균 승차
  피크/비피크  월 패널: 07~09시·18~20시 vs 나머지 시간 일평균 승차(2022 포함 → C1 사전추세 검정 가능)
  두 결과는 같은 역·같은 부트스트랩 ξ로 추정하므로 차이(휴일 − 평일, 비피크 − 피크)의 신뢰구간도 낸다.
  C1의 평일/휴일 사전추세는 2022 일별 자료가 있어야 검정된다(주 단위 사전 칸이 2023-01 두 주뿐).
서사 3 — 경계 흡수: 주 추정에서 뺀 경계역을 C1 시점(2024-01-27)부터 통근권 대조와 비교한다(전년 동기 대비).
  안쪽(서울) 경계역의 추가 증가 = 흡수, 바깥 역의 감소 = 유출. 바깥 이웃이 나중에 적용된 경계는
  적용 전·후 구간을 나눠 흡수가 풀렸는지(되돌아왔는지) 본다. 확대로 새로 생긴 경계(C4·C5 바깥)도 같은 방식.
출력 outputs/tables/het_timeofday.csv, boundary_absorption.csv, boundary_stations.csv
"""
from __future__ import annotations

import importlib.util
import sys

import numpy as np
import pandas as pd

from common import OUT_TABLES, ROOT

_spec = importlib.util.spec_from_file_location("did_cs", ROOT / "src" / "04_did_cs.py")
did = importlib.util.module_from_spec(_spec)
sys.modules["did_cs"] = did  # dataclass가 모듈을 sys.modules에서 찾는다
_spec.loader.exec_module(did)

C1_DATE = pd.Timestamp("2024-01-27")
C3_DATE, C4_DATE = pd.Timestamp("2024-08-10"), pd.Timestamp("2024-11-30")
C5_DATE, C6_DATE = pd.Timestamp("2025-05-03"), pd.Timestamp("2025-08-09")

# 경계 묶음: (노출 시작일, 해소일 또는 None, 역). 해소일 = 바깥 이웃이 적용된 날
# 제외: 김포공항(환승 허브·서해선 개통·코호트 혼재), 지축(소규모·서울 밖 C1), 양원·구리(구리역 적용일 미확인),
#       원종·부천종합운동장(2023-07 신설), 한국항공대·가천대(행락형 계절성)
BOUNDARY_GROUPS = {
    "안쪽·해소 없음 (도봉산·신내·금천구청·온수)": (C1_DATE, None, ["도봉산", "신내", "금천구청", "온수"]),
    "안쪽·복정 → 성남 C5로 해소": (C1_DATE, C5_DATE, ["복정"]),
    "안쪽·남태령·수색 → C4로 해소": (C1_DATE, C4_DATE, ["남태령", "수색"]),
    "안쪽·강일 → 하남 C6으로 해소": (C1_DATE, C6_DATE, ["강일"]),
    "안쪽·불암산 → 진접선 C3로 해소": (C1_DATE, C3_DATE, ["불암산"]),
    "바깥·끝내 미적용 (의정부·구리·남양주·안양·광명·부천·인천)": (
        C1_DATE, None, ["망월사", "회룡", "갈매", "별내", "도농", "양정", "석수", "관악", "광명", "역곡", "소사",
                        "계양", "검암"]),
    # 위 묶음 분해: 갈매·별내·도농·양정은 2024-08-10 별내선(8호선 연장, 경기 구간은 데이터 없음) 새 역과 가깝다
    "  └ 별내선 영향권 (갈매·별내·도농·양정)": (C1_DATE, None, ["갈매", "별내", "도농", "양정"]),
    "  └ 별내선 영향 밖 (망월사·회룡·석수·관악·광명·역곡·소사·계양·검암)": (
        C1_DATE, None, ["망월사", "회룡", "석수", "관악", "광명", "역곡", "소사", "계양", "검암"]),
    # 거리 기울기: 바깥 1~2역 다음의 두 역(주 대조군에 들어 있음) — 흡수가 있으면 약하게라도 줄어야 한다
    "바깥 2차 링 (의정부·가능·퇴계원·사릉·덕소·도심·안양·명학·부천·중동·청라국제도시)": (
        C1_DATE, None, ["의정부", "가능", "퇴계원", "사릉", "덕소", "도심", "안양", "명학", "부천", "중동",
                        "청라국제도시"]),
    "바깥·성남 태평·야탑 → C5 적용": (C1_DATE, C5_DATE, ["태평", "야탑"]),
    "바깥·과천 선바위·경마공원 → C4 적용": (C1_DATE, C4_DATE, ["선바위", "경마공원"]),
    "바깥·고양 강매·삼송·원흥 → C4 적용": (C1_DATE, C4_DATE, ["강매", "삼송", "원흥"]),
    "바깥·하남 미사·하남풍산 → C6 적용": (C1_DATE, C6_DATE, ["미사", "하남풍산"]),
    "새 경계 안쪽·탄현·정부과천청사 (C4 적용역)": (C4_DATE, None, ["탄현", "정부과천청사"]),
    "새 경계 안쪽·오리·이매 (C5 적용역)": (C5_DATE, None, ["오리", "이매"]),
    "새 경계 바깥·야당·운정·인덕원·평촌 (C4 인접 미적용)": (C4_DATE, None, ["야당", "운정", "인덕원", "평촌"]),
    "새 경계 바깥·죽전·보정·삼동·경기광주 (C5 인접 미적용)": (C5_DATE, None, ["죽전", "보정", "삼동", "경기광주"]),
}


# --------------------------------------------------------------------------- 서사 2

def timeofday() -> pd.DataFrame:
    pairs = {
        "주_평일/휴일": [did.aprime("het_work_week", outcome="work"), did.aprime("het_rest_week", outcome="rest")],
        "월_피크/비피크": [did.aprime("het_peak_month", freq="month", start="2022-01-01", outcome="peak"),
                       did.aprime("het_offpeak_month", freq="month", start="2022-01-01", outcome="offpeak")],
    }
    rows = []
    for family, (spec_a, spec_b) in pairs.items():
        fits = {}
        for spec in (spec_a, spec_b):
            cells, agg, G, labels = did.fit(spec)
            fits[spec.outcome] = (cells, agg, G, labels)
        (ca, aa, Ga, la), (cb, ab, Gb, lb) = fits[spec_a.outcome], fits[spec_b.outcome]
        assert list(Ga.index) == list(Gb.index), "두 결과의 역 순서가 달라 ξ를 공유할 수 없다"
        for label, sel in _params(ca, Ga).items():
            sel_b = _params(cb, Gb)[label]
            ea, sa, da = aa.estimate(sel)
            eb, sb, db = ab.estimate(sel_b)
            diff_draws = db - da
            rows.append({"family": family, "param": label,
                         spec_a.outcome: ea, f"{spec_a.outcome}_se": sa,
                         spec_b.outcome: eb, f"{spec_b.outcome}_se": sb,
                         "diff(b−a)": eb - ea, "diff_se": float(diff_draws.std(ddof=1))})
    return pd.DataFrame(rows)


def _params(cells: pd.DataFrame, G: pd.Series) -> dict[str, np.ndarray]:
    names = G.attrs["cohort_names"]
    coh = cells.g.map(names).to_numpy()
    post, k = (cells.e >= 0).to_numpy(), cells.k.to_numpy()
    return {
        "C1 1년차": (coh == "C1") & post & (k == 1),
        "C1 2년차": (coh == "C1") & post & (k == 2),
        "C1 적용 후 전체": (coh == "C1") & post,
        "C1 사전(placebo)": (coh == "C1") & ~post,
        "C5 적용 후": (coh == "C5") & post,
        "C5 사전(placebo)": (coh == "C5") & ~post,
    }


# --------------------------------------------------------------------------- 서사 3

def boundary_fit(stations: list[str], start: pd.Timestamp, freq: str, p_cache: dict):
    """경계역 묶음을 '가상 코호트'(노출 시작일)로, 통근권 대조를 대조로 둔 전년 동기 대비 CS-DiD."""
    if freq not in p_cache:
        p = did.load_long(freq, "on")
        p_cache[freq] = p[p.period >= pd.Timestamp("2022-01-01")] if freq == "month" else p
    p = p_cache[freq]
    u = p.drop_duplicates("complex").set_index("complex")[["cohort", "treat_date", "exclude_reason"]]
    ctrl = u[(u.cohort == "NT") & (u.exclude_reason.fillna("") == "")].assign(treat_date=pd.NaT)
    ctrl = ctrl.drop(index=stations, errors="ignore")  # 2차 링처럼 대조군 역을 묶음으로 쓸 때
    grp = u.loc[u.index.intersection(stations)].assign(cohort="B", treat_date=start)
    units = pd.concat([grp, ctrl]).assign(stratum="ALL")
    wide, G, labels = did.build_wide(p, units, freq)
    cells, contrib = did.att_gt(wide, G, "seasonal", "never", 52 if freq == "week" else 12)
    return cells, did.Aggregator(cells, contrib), labels, len(grp)


def boundary() -> tuple[pd.DataFrame, pd.DataFrame]:
    rows, st_rows, cache = [], [], {}
    for name, (start, relief, stations) in BOUNDARY_GROUPS.items():
        for freq in ("week", "month"):
            cells, agg, labels, n = boundary_fit(stations, start, freq, cache)
            t = pd.DatetimeIndex(labels.reindex(cells.t).to_numpy())
            post = (cells.e >= 0).to_numpy()
            windows = {"사전(placebo)": ~post}
            if relief is None:
                windows["노출 후 전체"] = post
            else:
                windows["해소 전(흡수 구간)"] = post & (t < relief)
                windows["해소 후"] = post & (t >= relief)
            for wname, mask in windows.items():
                est, se, _ = agg.estimate(mask)
                rows.append({"group": name, "freq": freq, "window": wname, "n_stations": n,
                             "est": est, "se": se if n > 1 else np.nan, "n_cells": int(mask.sum())})
        # 역별 점추정(주 자료, SE 없음 — 역 1곳은 부트스트랩 SE가 무효)
        for s in stations:
            cells, agg, labels, n = boundary_fit([s], start, "week", cache)
            if n == 0:
                continue
            t = pd.DatetimeIndex(labels.reindex(cells.t).to_numpy())
            post = (cells.e >= 0).to_numpy()
            rec = {"group": name, "station": s}
            if relief is None:
                rec["노출 후 전체"] = agg.estimate(post)[0]
            else:
                rec["해소 전"] = agg.estimate(post & (t < relief))[0]
                rec["해소 후"] = agg.estimate(post & (t >= relief))[0]
            st_rows.append(rec)
    return pd.DataFrame(rows), pd.DataFrame(st_rows)


def main() -> None:
    pd.set_option("display.width", 220)
    tod = timeofday()
    tod.to_csv(OUT_TABLES / "het_timeofday.csv", index=False, encoding="utf-8-sig")
    show = tod.copy()
    for col in show.columns[2:]:
        show[col] = (100 * show[col]).round(2)
    print("=== 서사 2: 시간대·요일 (%) ===")
    print(show.to_string(index=False))

    groups, stations = boundary()
    groups.to_csv(OUT_TABLES / "boundary_absorption.csv", index=False, encoding="utf-8-sig")
    stations.to_csv(OUT_TABLES / "boundary_stations.csv", index=False, encoding="utf-8-sig")
    g = groups.assign(est=(100 * groups.est).round(2), se=(100 * groups.se).round(2))
    print("\n=== 서사 3: 경계 흡수 (%) ===")
    print(g.pivot_table(index=["group", "window"], columns="freq", values=["est", "se"], sort=False).to_string())
    print("\n역별 점추정(주, %):")
    print((stations.set_index(["group", "station"]) * 100).round(1).to_string())


if __name__ == "__main__":
    main()
