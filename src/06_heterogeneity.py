"""처리군 내부 이질성(서사 2)과 경계 흡수(서사 3). 추정은 04_did_cs.py의 CS-DiD를 그대로 쓴다.

서사 2 — 무제한 정기권이 늘린 통행은 어느 시간·요일에 있나 (주 사양 A′ 조건):
  평일/휴일  주 패널: 공휴일 아닌 월~금 일평균 vs 토·일·공휴일 일평균 승차
  피크/비피크  월 패널: 07~09시·18~20시 vs 나머지 시간 일평균 승차(2022 포함 → C1 사전추세 검정 가능)
  두 결과는 같은 역·같은 부트스트랩 ξ로 추정하므로 차이(휴일 − 평일, 비피크 − 피크)의 신뢰구간도 낸다.
  C1의 평일/휴일 사전추세는 2022 일별 자료가 있어야 검정된다(주 단위 사전 칸이 2023-01 두 주뿐).
서사 3 — 경계 흡수: 주 추정에서 뺀 경계역을 C1 시점(2024-01-27)부터 통근권 대조와 비교한다(전년 동기 대비).
  안쪽(서울) 경계역의 추가 증가 = 흡수, 바깥 역의 감소 = 유출. 바깥 이웃이 나중에 적용된 경계는
  적용 전·후 구간을 나눠 흡수가 풀렸는지(되돌아왔는지) 본다. 확대로 새로 생긴 경계(C4·C5 바깥)도 같은 방식.
역 유형(AI 요소) — 2023(사전기간) 승차 시간대 구성 6구간 + 휴일/평일 비로 k-means(k는 4~6 중 실루엣 최대).
  유형마다 같은 유형의 통근권 대조와만 비교한 C1 ATT를 내고(대조 10곳 미만 유형은 추정 안 함),
  군집을 층으로 쓴 A′(오전 비중 사분위 대신)을 강건성으로 낸다.
실행: python src/06_heterogeneity.py [types] [tod] [boundary] [ring]  (인자 없으면 전부)
출력 outputs/tables/station_types.csv, station_type_centroids.csv, het_station_type*.csv, het_timeofday.csv,
     boundary_absorption.csv, boundary_stations.csv, ring_*.csv, ring1_*.csv / data/processed/station_types_2023.parquet
"""
from __future__ import annotations

import importlib.util
import sys
import warnings

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from common import DATA_PROCESSED, OUT_TABLES, ROOT

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
    "  └ 위에서 계양 제외 (사전추세 위반·검단연장 교란)": (
        C1_DATE, None, ["망월사", "회룡", "석수", "관악", "광명", "역곡", "소사", "검암"]),
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

def _panel(freq: str, outcome: str, p_cache: dict) -> pd.DataFrame:
    key = (freq, outcome)
    if key not in p_cache:
        p = did.load_long(freq, outcome)
        p_cache[key] = p[p.period >= pd.Timestamp("2022-01-01")] if freq == "month" else p
    return p_cache[key]


def joint_fits(groups: dict[str, list[str]], start: pd.Timestamp, freq: str, p_cache: dict,
               outcome: str = "on", extra_controls_out: list[str] | None = None):
    """여러 경계역 묶음을 같은 노출 시작일의 '가상 코호트'로 두고 통근권 대조와 전년 동기 대비 CS-DiD.
    모든 묶음이 같은 역 집합·순서를 쓰므로(다른 묶음 행은 결측) ξ가 같아 묶음 간 차이도 부트스트랩된다.
    반환: {묶음: (칸, Aggregator, 역 수)}, 기간 라벨."""
    p = _panel(freq, outcome, p_cache)
    u = p.drop_duplicates("complex").set_index("complex")[["cohort", "treat_date", "exclude_reason"]]
    members = [s for ss in groups.values() for s in ss] + list(extra_controls_out or [])
    ctrl = u[(u.cohort == "NT") & (u.exclude_reason.fillna("") == "")].drop(index=members, errors="ignore")
    grp_idx = u.index.intersection([s for ss in groups.values() for s in ss])
    units = pd.concat([u.loc[grp_idx].assign(cohort="B", treat_date=start),
                       ctrl.assign(treat_date=pd.NaT)]).assign(stratum="ALL")
    wide, G, labels = did.build_wide(p, units, freq)
    out = {}
    for name, ss in groups.items():
        mine = wide.index.isin(ss)
        others = wide.index.isin(grp_idx) & ~mine
        w = wide.copy()
        w.loc[others] = np.nan  # 다른 묶음 역은 이번 추정에서 빠진다(대조로도 쓰이지 않게)
        Gi = G.copy()
        Gi[others] = np.nan
        Gi.attrs.update(G.attrs)
        cells, contrib = did.att_gt(w, Gi, "seasonal", "never", 52 if freq == "week" else 12)
        out[name] = (cells, did.Aggregator(cells, contrib), int(mine.sum()))
    return out, labels


def boundary_fit(stations: list[str], start: pd.Timestamp, freq: str, p_cache: dict, outcome: str = "on"):
    """경계역 묶음 하나를 '가상 코호트'(노출 시작일)로, 통근권 대조를 대조로 둔 전년 동기 대비 CS-DiD."""
    fits, labels = joint_fits({"B": stations}, start, freq, p_cache, outcome)
    cells, agg, n = fits["B"]
    return cells, agg, labels, n


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


# --------------------------------------------------------------------------- 서사 3 보강

# 1차 링: 끝내 미적용 경계의 바깥 1~2역(별내선 영향권 제외). 계양은 사전추세 위반(−13%)과 2025-06-28
# 인천1호선 검단연장(계양 환승) 교란이 겹쳐 묶음에서 빼고 역별 표에만 남긴다
RING1_ALL = ["망월사", "회룡", "석수", "관악", "광명", "역곡", "소사", "계양", "검암"]
RING1 = [s for s in RING1_ALL if s != "계양"]
RING2 = ["의정부", "가능", "퇴계원", "사릉", "덕소", "도심", "안양", "명학", "부천", "중동", "청라국제도시"]
POLICY_WINDOWS = [  # 1차 링 이탈 시점 판별용 구간 (시작 포함, 끝 미포함)
    ("① 출시~본사업 전", "2024-01-27", "2024-07-01"),
    ("② 본사업(청년할인·관광권)~후불카드 전", "2024-07-01", "2024-11-30"),
    ("③ 후불카드·고양과천 확대~검단연장 전", "2024-11-30", "2025-06-28"),
    ("④ 인천1호선 검단연장 뒤", "2025-06-28", "2027-01-01"),
]
STATION_EVENTS = {  # 역별로 확인한(또는 알려진) 국지 사건
    "계양": "인천1호선 검단연장 개통 2025-06-28(계양 환승, 경향신문 2025-06-18)",
    "검암": "인천2호선 환승역(기존), 검단 신도시 인접 — 연장선 영향 가능",
    "소사": "서해선 환승 개통 2023-07-01(사전기간)",
    "회룡": "의정부경전철 환승역(기존)",
}
EXPANDED_OUT = {  # 바깥 1차 링 중 나중에 적용된 묶음: (적용일, 역)
    "성남 태평·야탑(C5)": (C5_DATE, ["태평", "야탑"]),
    "과천 선바위·경마공원(C4)": (C4_DATE, ["선바위", "경마공원"]),
    "고양 강매·삼송·원흥(C4)": (C4_DATE, ["강매", "삼송", "원흥"]),
}


def _window_masks(cells: pd.DataFrame, labels: pd.Series) -> dict[str, np.ndarray]:
    t = pd.DatetimeIndex(labels.reindex(cells.t).to_numpy())
    post = (cells.e >= 0).to_numpy()
    out = {"사전(placebo)": ~post, "노출 후 전체": post}
    for name, a, b in POLICY_WINDOWS:
        out[name] = post & (t >= pd.Timestamp(a)) & (t < pd.Timestamp(b))
    return out


def card_monthly() -> pd.Series:
    """누적 충전 기점을 월말로 선형 보간해 월별 충전 건수(근사)를 만든다."""
    m = pd.read_csv(ROOT / "data" / "reference" / "card_uptake_milestones.csv", parse_dates=["date"])
    m = m[m.metric == "누적 충전(건)"].set_index("date").value
    months = pd.date_range("2024-01-31", "2026-04-30", freq="ME")
    cum = pd.Series(np.interp(months.asi8, m.index.asi8, m.to_numpy()), index=months)
    return cum.diff().fillna(cum.iloc[0]).rename("charges").set_axis(months.to_period("M"))


def ring1_timing(cache: dict) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """1차·2차 링의 정책 사건 구간별 이탈과 월 event-study, 카드 충전 근사 계열과의 상관."""
    rows, events = [], {}
    fits_w, lab_w = joint_fits({"1차 링": RING1, "2차 링": RING2}, C1_DATE, "week", cache)
    fits_m, lab_m = joint_fits({"1차 링": RING1, "2차 링": RING2}, C1_DATE, "month", cache)
    for name in ("1차 링", "2차 링"):
        for freq, (cells, agg, n), lab in (("week", fits_w[name], lab_w), ("month", fits_m[name], lab_m)):
            for wname, mask in _window_masks(cells, lab).items():
                est, se, _ = agg.estimate(mask)
                rows.append({"group": name, "freq": freq, "window": wname, "est": est, "se": se, "n": n,
                             "n_cells": int(mask.sum())})
        cells, agg, _ = fits_m[name]
        ev = did.event_study(agg, 1)
        ev["month"] = [(pd.Timestamp("2024-02-01") + pd.DateOffset(months=int(e))).to_period("M") for e in ev.e_start]
        ev["group"] = name
        events[name] = ev
    # 카드 충전(근사)과 1차 링 월별 이탈의 상관 — 사후 월만
    ev = events["1차 링"].set_index("month")
    cm = card_monthly()
    j = ev.join(cm, how="inner")
    j = j[j.e_start >= 0]
    corr = {"n_months": len(j), "pearson": float(j.est.corr(j.charges)),
            "spearman": float(j.est.corr(j.charges, method="spearman"))}
    return pd.DataFrame(rows), pd.concat(events.values(), ignore_index=True), corr


def ring1_stations(cache: dict) -> pd.DataFrame:
    """1차 링 9역 각각의 추정치(구간별)와 플라세보 순위, leave-one-out."""
    # 플라세보 분포: 통근권 대조역을 한 곳씩 가짜 처리역으로(나머지 대조와 비교)
    p = _panel("week", "on", cache)
    u = p.drop_duplicates("complex").set_index("complex")
    controls = list(u.index[(u.cohort == "NT") & (u.exclude_reason.fillna("") == "")])
    placebo = []
    for s in controls:
        cells, agg, lab, n = boundary_fit([s], C1_DATE, "week", cache)
        placebo.append(agg.estimate((cells.e >= 0).to_numpy())[0])
    placebo = np.array(placebo)
    rows = []
    for s in RING1_ALL:
        cells, agg, lab, n = boundary_fit([s], C1_DATE, "week", cache)
        masks = _window_masks(cells, lab)
        rec = {"station": s, "event": STATION_EVENTS.get(s, "")}
        for wname, mask in masks.items():
            rec[wname] = agg.estimate(mask)[0]
        rec["placebo_rank_p"] = float((placebo <= rec["노출 후 전체"]).mean())
        loo = [x for x in RING1 if x != s] if s in RING1 else RING1
        c2, a2, l2, _ = boundary_fit(loo, C1_DATE, "week", cache)
        rec["loo_est"], rec["loo_se"] = a2.estimate((c2.e >= 0).to_numpy())[:2]
        rows.append(rec)
    out = pd.DataFrame(rows)
    out.attrs["placebo_sd"] = float(placebo.std(ddof=1))
    out.attrs["placebo_n"] = len(placebo)
    return out


def ring1_honest(cache: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """1차 링 이탈에 대한 HonestDiD 상대적 크기 제약 — 1차 링 자신의 2022→23 사전 흐름을 벤치마크로."""
    cells, agg, labels, _ = boundary_fit(RING1, C1_DATE, "week", cache)
    G = pd.Series(dtype=float)
    G.attrs["cohort_names"] = {int(cells.g.iloc[0]): "C1"}  # did.honest_rm이 'C1' 코호트를 찾는다
    return did.honest_rm({"agg": agg, "G": G, "labels": labels},
                         {"1차 링 자체 사전 흐름(2022→23)": "2022-01-01",
                          "1차 링 사전 흐름(거리두기 해제 뒤 2022-05~)": "2022-05-01"})


def ring_alighting(cache: dict) -> pd.DataFrame:
    """1차·2차 링의 하차 변화(카드 이용자는 범위 밖 하차도 피하므로 승차와 같이 줄어야 정합)."""
    rows = []
    for outcome in ("on", "off"):
        fits, lab = joint_fits({"1차 링": RING1, "2차 링": RING2}, C1_DATE, "week", cache, outcome=outcome)
        for name, (cells, agg, n) in fits.items():
            for wname, mask in _window_masks(cells, lab).items():
                if wname in ("사전(placebo)", "노출 후 전체"):
                    est, se, _ = agg.estimate(mask)
                    rows.append({"group": name, "outcome": {"on": "승차", "off": "하차"}[outcome],
                                 "window": wname, "est": est, "se": se})
    return pd.DataFrame(rows)


def nonrecovery(cache: dict) -> pd.DataFrame:
    """확대 뒤 미회복 설명 후보 중 자료로 가를 수 있는 것.
    (가) 공통 추세: 나중에 적용된 바깥 역과 끝내 미적용인 1차 링의 차이가 적용 전후로 달라졌나
         [(L − N)적용 후 − (L − N)적용 전] — 0이면 확대가 이 역들을 되돌리지 못했고, 경계 공통 추세와 같다
    (나) 습관 고착: 적용 뒤 월별 격차에 회복 기울기가 있나(월당 %p, 기울기 > 0이면 서서히 회복 중)"""
    rows = []
    for name, (exp_date, stations) in EXPANDED_OUT.items():
        fits, lab = joint_fits({"L": stations, "N": RING1}, C1_DATE, "month", cache)
        (cl, al, nl), (cn, an, nn) = fits["L"], fits["N"]
        t = pd.DatetimeIndex(lab.reindex(cl.t).to_numpy())
        tn = pd.DatetimeIndex(lab.reindex(cn.t).to_numpy())
        # 월 자료에서 적용일이 월 중간이면 그 달(부분 처리)은 전·후 어디에도 넣지 않는다
        exp_month = exp_date.to_period("M").to_timestamp()
        first_full = exp_month if exp_date.day == 1 else exp_month + pd.offsets.MonthBegin(1)
        pre_l, post_l = (cl.e >= 0).to_numpy() & (t < exp_month), (t >= first_full)
        pre_n, post_n = (cn.e >= 0).to_numpy() & (tn < exp_month), (tn >= first_full)
        el1, _, dl1 = al.estimate(pre_l)
        el2, _, dl2 = al.estimate(post_l)
        en1, _, dn1 = an.estimate(pre_n)
        en2, _, dn2 = an.estimate(post_n)
        ddd = (el2 - en2) - (el1 - en1)
        ddd_draws = (dl2 - dn2) - (dl1 - dn1)
        # 기울기: 적용 뒤 월별 L 추정치를 경과 월에 회귀(부트스트랩 ξ로 SE)
        months = sorted(set(cl.t[post_l]))
        m_idx = np.arange(len(months), dtype=float)
        ests, draws = [], []
        for tt in months:
            e, _, d = al.estimate((cl.t == tt).to_numpy())
            ests.append(e)
            draws.append(e + d)
        X = m_idx - m_idx.mean()
        slope = float(np.dot(X, np.array(ests)) / np.dot(X, X)) if len(months) > 2 else np.nan
        slope_draws = (np.column_stack(draws) @ X) / np.dot(X, X) if len(months) > 2 else np.full(1, np.nan)
        rows.append({"group": name, "n_L": nl, "적용 전(L)": el1, "적용 후(L)": el2,
                     "적용 전(끝내 미적용 1차 링)": en1, "적용 후(끝내 미적용 1차 링)": en2,
                     "(가) 확대의 차등 효과": ddd, "(가)_se": float(ddd_draws.std(ddof=1)),
                     "(나) 적용 뒤 월 기울기(%p/월)": slope,
                     "(나)_se": float(np.nanstd(slope_draws - slope_draws.mean(), ddof=1)),
                     "적용 뒤 개월": len(months)})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- 역 유형(AI 요소)

TYPE_BINS = {"새벽(05~06시)": [5, 6], "오전 첨두(07~08시)": [7, 8], "낮(09~16시)": list(range(9, 17)),
             "오후 첨두(17~19시)": [17, 18, 19], "저녁(20~22시)": [20, 21, 22], "심야(23~04시)": [23, 0, 1, 2, 3, 4]}
TYPE_K = (4, 5, 6)           # 해석 가능한 유형 수 안에서 실루엣이 가장 큰 k
TYPE_SEED = 20260925
TYPE_NAMES = [               # 차례로, 남은 군집 중 기준 열 중심값이 가장 큰 군집에 이름을 붙인다. 나머지는 혼합형
    ("업무형", "오후 첨두(17~19시)"),
    ("상업·여가형", "저녁(20~22시)"),
    ("주거·출근형", "오전 첨두(07~08시)"),
    ("생활·한낮형", "낮(09~16시)"),
]
MIN_TYPE_CONTROLS = 10       # 유형 안 통근권 대조 역이 이보다 적으면 그 유형의 ATT는 내지 않는다


def type_features() -> pd.DataFrame:
    """역 유형 특징(2023 = 사전기간만): 승차 시간대 구성 6구간 비중 + 휴일/평일 일평균 승차 비."""
    prof = pd.read_parquet(DATA_PROCESSED / "station_profile_2023.parquet").set_index("complex")
    X = pd.DataFrame({k: prof[[f"h{h}" for h in v]].sum(axis=1) for k, v in TYPE_BINS.items()})
    w = pd.read_parquet(DATA_PROCESSED / "panel_week.parquet")
    w = w[(w.week >= "2023-01-07") & (w.week < "2024-01-06")]
    s = w.groupby("complex")[["on_work", "n_work", "on_rest", "n_rest"]].sum()
    X["휴일/평일 비"] = (s.on_rest / s.n_rest) / (s.on_work / s.n_work)
    return X.dropna()


def station_types() -> tuple[pd.DataFrame, pd.DataFrame]:
    """k-means 역 유형. 주 표본(C1·통근권 대조)으로 표준화·학습하고 나머지 역은 가장 가까운 중심에 배정한다.
    결과는 data/processed/station_types_2023.parquet(04의 strata='cluster'가 읽음)."""
    X = type_features()
    u = did.load_long("week", "on").drop_duplicates("complex").set_index("complex")[["cohort", "exclude_reason"]]
    reason = u.exclude_reason.fillna("")
    ref = X.index.intersection(u.index[u.cohort.isin(["C1", "NT"]) & (reason == "")])
    scaler = StandardScaler().fit(X.loc[ref])
    Z = scaler.transform(X.loc[ref])
    fits = {k: KMeans(k, n_init=50, random_state=TYPE_SEED).fit(Z) for k in TYPE_K}
    sil = {k: float(silhouette_score(Z, m.labels_)) for k, m in fits.items()}
    k = max(sil, key=sil.get)
    km = fits[k]
    cen = pd.DataFrame(scaler.inverse_transform(km.cluster_centers_), columns=X.columns)
    names, left = {}, set(range(k))
    for name, col in TYPE_NAMES:
        if left:
            c = max(left, key=lambda c: cen.at[c, col])
            names[c] = name
            left.discard(c)
    for i, c in enumerate(sorted(left)):
        names[c] = "혼합형" if i == 0 else f"혼합형{i + 1}"
    types = pd.DataFrame({"complex": X.index, "type": pd.Series(km.predict(scaler.transform(X))).map(names).to_numpy()})
    types["cohort"] = u.cohort.reindex(types.complex).to_numpy()
    types["in_main_sample"] = types.complex.isin(ref)
    types.to_parquet(DATA_PROCESSED / "station_types_2023.parquet", index=False)
    lab = types.set_index("complex").loc[ref]
    cen.insert(0, "type", [names[c] for c in range(k)])
    cen["n_C1"] = [int(((lab.type == names[c]) & (lab.cohort == "C1")).sum()) for c in range(k)]
    cen["n_NT"] = [int(((lab.type == names[c]) & (lab.cohort == "NT")).sum()) for c in range(k)]
    cen["예시 역(C1)"] = [", ".join(lab.index[(lab.type == names[c]) & (lab.cohort == "C1")][:6]) for c in range(k)]
    cen.attrs.update(k=k, silhouette=sil)
    return types, cen


def _station_effects(spec) -> pd.DataFrame:
    """처리 역별 1·2년차 평균 효과(칸마다 같은 층 대조 평균과의 차이를 역별로 평균). 소수 역이 끄는지 보는 진단."""
    wide, G, _ = did.to_wide(spec)
    Y, Gv, strata = wide.to_numpy(), G.to_numpy(), G.attrs["strata"]
    out = {}
    for g in np.unique(Gv[~np.isnan(Gv)]).astype(int):
        tr = Gv == g
        acc = {1: [], 2: []}
        for t in range(g, Y.shape[1]):
            k = int(np.floor((t - (g - 52)) / 52))
            if k not in acc:
                continue
            b = t - 52 * k
            dy = Y[:, t] - Y[:, b]
            e = np.full(len(dy), np.nan)
            for s in np.unique(strata[tr]):
                cc = np.isnan(Gv) & (strata == s) & ~np.isnan(dy)
                sel = tr & (strata == s)
                if cc.sum() >= 2:
                    e[sel] = dy[sel] - dy[cc].mean()
            acc[k].append(e)
        for k, rows in acc.items():
            if rows:
                with warnings.catch_warnings():  # 칸이 모두 결측인 역(대조 층 부족)은 NaN으로 둔다
                    warnings.simplefilter("ignore", RuntimeWarning)
                    out[f"{k}년차"] = pd.Series(np.nanmean(np.vstack(rows), axis=0), index=wide.index)[tr]
    return pd.DataFrame(out)


def type_effects(cen: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """유형별 C1 ATT(같은 유형의 통근권 대조와만 비교) + 군집 층화판 A′(대조가 부족한 유형은 처리에서 뺌).
    역별 효과의 중앙값·상하위 5% 절사 평균을 함께 낸다(재건축 입주 같은 국지 사건이 몇 역을 끌어올리는지 진단)."""
    all_types = tuple(cen.type)
    thin = tuple(cen.type[cen.n_NT < MIN_TYPE_CONTROLS])
    pick = {"1년차": "C1_year1(적용 후 1년차)", "2년차": "C1_year2(적용 후 2년차)",
            "적용 후 전체": "C1_post", "사전(placebo)": "C1_pre(placebo)"}
    rows, per_station = [], []

    def add(label, spec, n_c1, n_nt):
        cells, agg, G, labels = did.fit(spec)
        s = did.summarize(agg, labels, G).set_index("param")
        row = {"type": label, "n_C1": n_c1, "n_NT": n_nt}
        for k, p in pick.items():
            row[k], row[f"{k}_se"] = s.at[p, "est"], s.at[p, "se"]
        st = _station_effects(spec)
        for k in ("1년차", "2년차"):
            x = st[k].dropna()
            lo, hi = x.quantile([0.05, 0.95])
            row[f"{k}_역별 중앙값"] = float(x.median())
            row[f"{k}_5% 절사 평균"] = float(x[(x >= lo) & (x <= hi)].mean())
        rows.append(row)
        per_station.append(st.assign(type=label).rename_axis("complex").reset_index())

    for r in cen.itertuples():
        if r.type in thin:
            rows.append({"type": r.type, "n_C1": r.n_C1, "n_NT": r.n_NT, "note": "대조 역 부족 — 추정 안 함"})
            continue
        add(r.type, did.Spec(f"type_{r.type}", cohorts=("C1",), strata="cluster", stratify=("C1",),
                             drop_treated_strata=tuple(t for t in all_types if t != r.type)), r.n_C1, r.n_NT)
    keep = cen[~cen.type.isin(thin)]
    add(f"A′ 군집 층화({'·'.join(thin)} 제외)",
        did.Spec("Aprime_cluster_week", cohorts=("C1",), strata="cluster", stratify=("C1",), drop_treated_strata=thin),
        int(keep.n_C1.sum()), int(keep.n_NT.sum()))
    stations = pd.concat(per_station[:-1], ignore_index=True)  # 마지막(A′ 군집 층화)은 유형별과 역이 겹친다
    return pd.DataFrame(rows), stations


def main() -> None:
    pd.set_option("display.width", 220)
    parts = set(sys.argv[1:]) or {"types", "tod", "boundary", "ring"}
    if "types" in parts:
        types, cen = station_types()
        types.to_csv(OUT_TABLES / "station_types.csv", index=False, encoding="utf-8-sig")
        cen.to_csv(OUT_TABLES / "station_type_centroids.csv", index=False, encoding="utf-8-sig")
        print(f"=== 역 유형(k-means, k={cen.attrs['k']}, 실루엣 "
              + ", ".join(f"k={k}: {v:.3f}" for k, v in cen.attrs["silhouette"].items()) + ") ===")
        show = cen.copy()
        for col in list(TYPE_BINS) + ["휴일/평일 비"]:
            show[col] = show[col].round(3)
        print(show.to_string(index=False))
        te, te_st = type_effects(cen)
        te.to_csv(OUT_TABLES / "het_station_type.csv", index=False, encoding="utf-8-sig")
        te_st.to_csv(OUT_TABLES / "het_station_type_stations.csv", index=False, encoding="utf-8-sig")
        num = [c for c in te.columns if c not in ("type", "n_C1", "n_NT", "note")]
        print("\n=== 유형별 C1 ATT (%) ===")
        print(te.assign(**{c: (100 * te[c]).round(2) for c in num}).to_string(index=False))
    if "tod" in parts:
        _main_tod()
    if "boundary" in parts:
        _main_boundary()
    if "ring" in parts:
        _main_ring()


def _main_tod() -> None:
    tod = timeofday()
    tod.to_csv(OUT_TABLES / "het_timeofday.csv", index=False, encoding="utf-8-sig")
    show = tod.copy()
    for col in show.columns[2:]:
        show[col] = (100 * show[col]).round(2)
    print("=== 서사 2: 시간대·요일 (%) ===")
    print(show.to_string(index=False))


def _main_boundary() -> None:
    groups, stations = boundary()
    groups.to_csv(OUT_TABLES / "boundary_absorption.csv", index=False, encoding="utf-8-sig")
    stations.to_csv(OUT_TABLES / "boundary_stations.csv", index=False, encoding="utf-8-sig")
    g = groups.assign(est=(100 * groups.est).round(2), se=(100 * groups.se).round(2))
    print("\n=== 서사 3: 경계 흡수 (%) ===")
    print(g.pivot_table(index=["group", "window"], columns="freq", values=["est", "se"], sort=False).to_string())
    print("\n역별 점추정(주, %):")
    print((stations.set_index(["group", "station"]) * 100).round(1).to_string())


def _main_ring() -> None:
    cache: dict = {}
    windows, events, corr = ring1_timing(cache)
    windows.to_csv(OUT_TABLES / "ring_timing_windows.csv", index=False, encoding="utf-8-sig")
    events.assign(month=events.month.astype(str)).to_csv(OUT_TABLES / "ring_event_month.csv", index=False,
                                                         encoding="utf-8-sig")
    print("\n=== 서사 3 보강 ①: 1·2차 링 정책 사건 구간별 이탈 (%) ===")
    w = windows.assign(est=(100 * windows.est).round(2), se=(100 * windows.se).round(2))
    print(w.pivot_table(index=["group", "window"], columns="freq", values=["est", "se"], sort=False).to_string())
    print(f"카드 충전(근사 월별)과 1차 링 월 이탈의 상관: {corr}")

    st = ring1_stations(cache)
    st.to_csv(OUT_TABLES / "ring1_stations.csv", index=False, encoding="utf-8-sig")
    print(f"\n=== 서사 3 보강 ②: 1차 링 역별·leave-one-out (%) — 플라세보 대조역 {st.attrs['placebo_n']}곳의 "
          f"표준편차 {100 * st.attrs['placebo_sd']:.2f}%p ===")
    num = st.columns.difference(["station", "event", "placebo_rank_p"])
    print(st.assign(**{c: (100 * st[c]).round(2) for c in num}).to_string(index=False))

    hg, hb = ring1_honest(cache)
    hg.to_csv(OUT_TABLES / "ring1_honest_rm.csv", index=False, encoding="utf-8-sig")
    hb.to_csv(OUT_TABLES / "ring1_honest_rm_breakdown.csv", index=False, encoding="utf-8-sig")
    print("\n=== 서사 3 보강 ③′: 1차 링 HonestDiD (%) ===")
    show = hg[hg.Mbar.isin([0, 0.5, 1, 1.5, 2])].copy()
    for col in ["D_annual", "est", "id_lo", "id_hi", "ci_lo", "ci_hi"]:
        show[col] = (100 * show[col]).round(2)
    print(show.drop(columns=["se", "k_mean"]).to_string(index=False))
    print(hb.assign(est=(100 * hb.est).round(2)).to_string(index=False))

    al = ring_alighting(cache)
    al.to_csv(OUT_TABLES / "ring_alighting.csv", index=False, encoding="utf-8-sig")
    print("\n=== 서사 3 보강 ④: 승차·하차 (%) ===")
    print(al.assign(est=(100 * al.est).round(2), se=(100 * al.se).round(2)).to_string(index=False))

    nr = nonrecovery(cache)
    nr.to_csv(OUT_TABLES / "ring_nonrecovery.csv", index=False, encoding="utf-8-sig")
    print("\n=== 서사 3 보강 ⑤: 확대 뒤 미회복 (%, 기울기는 %p/월) ===")
    num = nr.columns.difference(["group", "n_L", "적용 뒤 개월"])
    print(nr.assign(**{c: (100 * nr[c]).round(2) for c in num}).to_string(index=False))


if __name__ == "__main__":
    main()
