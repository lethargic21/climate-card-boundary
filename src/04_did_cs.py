"""Callaway & Sant'Anna(2021) staggered DiD — 공변량 없음, 물리적 역 단위.

ATT(g,t) = E[Y_t − Y_b | G=g] − E[Y_t − Y_b | C]
- Y: log 승차(주 합계, 평일·휴일 일평균) 또는 log 월 일평균 승차(전체·피크·비피크) — Spec.outcome
- C: never-treated(주), 선택 시 + not-yet-treated(G > max(t, b))
- 기준기간 b
    universal  b = g − 1 (처리 직전 기간)
    seasonal   b = 처리 직전 한 주기(52주/12개월) 안의 같은 주차·월 → 전년 동기 대비(역별 계절성 제거).
               처리 직전 한 주기 안의 t는 b = t라 정의상 0이다.
- 층화: stratify에 든 코호트는 역 유형 층 안에서만 처리·대조를 비교하고 처리 역 수로 가중해 합친다
  (이산 공변량을 포화시킨 CS outcome regression과 같다) — 조건부 평행추세.
추론: 역 단위 multiplier bootstrap(영향함수, Rademacher, B=999). 역이 곧 클러스터다.
설·추석 연휴가 낀 주는 결측으로 둔다.

주 사양 A′(2026-09-25 채택): 처리 = C1(업무·관광형 제외, 역 유형 층화) + C5(층화 없음).
C4 과천은 과천역 1곳뿐이라 사례로만, C6(하남)은 보조 분석. 대조 = 통근권 never-treated.

HonestDiD 상대적 크기 제약 Δ^RM(M̄) (Rambachan & Roth 2023):
전년 동기 대비 설계에서는 편향이 1년 단위로 쌓인다. 기준 연도로부터 k년 뒤 편향 δ_k의 연간 변화가
사전기간 연간 변화(벤치마크 D)의 M̄배를 넘지 않는다고 두면 |δ_k| ≤ k·M̄·D이고,
식별 구간은 β_k ± k·M̄·D다. 신뢰구간은 하한·상한을 같은 부트스트랩으로 뽑아
[하한의 2.5% 분위, 상한의 97.5% 분위]로 잡는다(ARP 조건부 검정의 근사).

사용 예
  python src/04_did_cs.py            # 주 사양·강건성·2019 진단·HonestDiD
  python src/04_did_cs.py --preview  # 층화 미리보기(기록용)
출력 outputs/tables/cs_{spec}_{cells,summary,event}.csv, diag_2019_baseline.csv, honest_rm*.csv
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass

import numpy as np
import pandas as pd

from common import DATA_PROCESSED, OUT_TABLES

TREATED_COHORTS = ("C1", "C4", "C5", "C6")
GWACHEON = ("대공원", "과천")
KPASS_START = pd.Timestamp("2024-05-01")
B_BOOT = 999
SEED = 20260925
MBARS = (0.0, 0.5, 1.0, 1.5, 2.0)


@dataclass
class Spec:
    name: str
    freq: str = "week"                   # week | month
    base: str = "seasonal"               # seasonal | universal
    control: str = "never"               # never | notyet
    controls: str = "main"               # main(통근권) | full(+행락형) | with_ring2(+경계 2차 링, 이전 기준)
    start: str | None = None             # 추정 표본 시작(예: '2022-01-01')
    outcome: str = "on"                  # 주: on | work | rest · 월: on | peak | offpeak
    cohorts: tuple = TREATED_COHORTS
    c4_units: tuple | None = None        # C4 처리 역 제한(예: 과천만)
    strata: str | None = None            # 'am_quartile'
    stratify: tuple = ()                 # 층 안에서만 비교할 코호트
    drop_treated_strata: tuple = ()      # stratify 코호트의 처리 역 중 뺄 층
    drop_strata: tuple = ()              # 처리·대조 모두에서 뺄 층(미리보기용)
    drop_controls: tuple = ()            # 대조군에서 뺄 역(예: 경계 2차 링)
    drop_months: tuple = ()              # 월 자료에서 뺄 달(설·추석이 해마다 다른 달에 드는 1·2·9·10월 등)


HOLIDAY_MONTHS = (1, 2, 9, 10)  # 설(1~2월)·추석(9~10월)이 해마다 다른 달에 든다 — 월 자료 전년 동기 비교를 어긋나게 함


def aprime(name: str, **kw) -> Spec:
    """주 사양 A′: C1 층화 + 업무·관광형 제외, C5는 층화 없음.
    C4 과천은 행락형 대공원을 빼면 과천역 1곳이라(처리 역 1곳이면 부트스트랩 SE가 무효) 따로 기술하고,
    C6은 보조 분석으로 돌린다."""
    opts = dict(cohorts=("C1", "C5"), strata="am_quartile",
                stratify=("C1",), drop_treated_strata=("Q1_업무관광",))
    opts.update(kw)
    return Spec(name, **opts)


# --------------------------------------------------------------------------- 자료

def load_long(freq: str, outcome: str) -> pd.DataFrame:
    """역 × 기간 긴 표에 y(log 결과변수)와 period를 붙인다."""
    if freq == "week":
        p = pd.read_parquet(DATA_PROCESSED / "panel_week.parquet")
        num = {"on": p.on, "off": p.off, "work": p.on_work / p.n_work, "rest": p.on_rest / p.n_rest}[outcome]
        p["y"] = np.log(num.where(num > 0)).where(~p.holiday_week)
        p["period"] = p.week
    else:
        p = pd.read_parquet(DATA_PROCESSED / "panel_month.parquet")
        num = {"on": p.on, "peak": p.on_peak, "offpeak": p.on_offpeak}[outcome] / p.days
        p["y"] = np.log(num.where(num > 0))
        p["period"] = p.month
    return p


def station_strata(kind: str, units: pd.DataFrame) -> pd.Series:
    """사전기간(2023) 시간대 프로필로 정한 역 유형. 경계값은 사양과 무관하게
    C1·통근권 대조 주 표본 역으로 고정한다."""
    if kind == "cluster":  # 06_heterogeneity.py의 역 유형 군집(2023 프로필 k-means)
        path = DATA_PROCESSED / "station_types_2023.parquet"
        if not path.exists():
            raise FileNotFoundError(f"{path.name} 없음 — 06_heterogeneity.py를 먼저 실행")
        return pd.read_parquet(path).set_index("complex")["type"]
    prof = pd.read_parquet(DATA_PROCESSED / "station_profile_2023.parquet").set_index("complex")
    if kind != "am_quartile":
        raise ValueError(kind)
    am = prof.h7 + prof.h8
    ref = units.index[units.cohort.isin(["C1", "NT"]) & (units.exclude_reason.fillna("") == "")]
    cuts = am.loc[am.index.intersection(ref)].quantile([0.25, 0.5, 0.75]).to_numpy()
    labels = np.array(["Q1_업무관광", "Q2", "Q3", "Q4_주거"])
    # side="left": 경계값과 같은 역은 아래 층(pd.qcut의 오른쪽 닫힌 구간과 같게)
    return pd.Series(labels[np.searchsorted(cuts, am.to_numpy(), side="left")], index=am.index)


def select_units(p: pd.DataFrame, spec: Spec) -> pd.DataFrame:
    """처리·대조 역과 코호트·처리일·층. 행락형(leisure)만 걸린 NT 역은 controls='full'일 때 넣는다."""
    u = p.drop_duplicates("complex").set_index("complex")[["cohort", "treat_date", "exclude_reason"]]
    reason = u.exclude_reason.fillna("")
    treated = u.cohort.isin(spec.cohorts) & (reason == "")
    if spec.c4_units is not None:
        treated &= (u.cohort != "C4") | u.index.isin(spec.c4_units)
    ok_ctrl = {"main": [""], "full": ["", "leisure"], "with_ring2": ["", "boundary_ring2"]}[spec.controls]
    control = (u.cohort == "NT") & reason.isin(ok_ctrl) & ~u.index.isin(spec.drop_controls)
    strata = station_strata(spec.strata, u) if spec.strata else None
    u = u[treated | control].copy()
    u["stratum"] = strata.reindex(u.index).fillna("NA").to_numpy() if strata is not None else "ALL"
    drop = u.stratum.isin(spec.drop_strata) | (
        u.cohort.isin(spec.stratify) & u.stratum.isin(spec.drop_treated_strata))
    return u[~drop]


def build_wide(p: pd.DataFrame, units: pd.DataFrame, freq: str, stratify: tuple = ()):
    """log 결과변수 행렬(역 × 기간 정수 인덱스), 처리 기간 인덱스 G(NT는 NaN), 기간 라벨.
    G.attrs: strata(역별 층), cohort_names(g → 코호트), stratify(층화할 g 집합)."""
    p = p[p.complex.isin(units.index)]
    labels = pd.Index(sorted(p.period.unique()))
    if freq == "week":
        idx = ((labels - labels[0]).days // 7).astype(int)
        g_idx = lambda d: (d - labels[0]).days // 7  # noqa: E731
    else:
        idx = (labels.year * 12 + labels.month - (labels[0].year * 12 + labels[0].month)).astype(int)
        g_idx = lambda d: (d.year * 12 + d.month) - (labels[0].year * 12 + labels[0].month)  # noqa: E731
    wide = p.pivot_table(index="complex", columns="period", values="y")
    wide.columns = pd.Index(idx[labels.get_indexer(wide.columns)])
    wide = wide.reindex(columns=range(idx.max() + 1))
    info = units.loc[wide.index]
    G = info.treat_date.map(lambda d: g_idx(d) if pd.notna(d) else np.nan).astype(float)
    # 월 단위에서 처리일이 월 중간이면 그 달은 부분 처리 → 처리 역의 그 달을 결측으로 두고 다음 달을 첫 처리 월로
    if freq == "month":
        partial = (info.treat_date.dt.day > 1).to_numpy()
        for row, g in enumerate(G.to_numpy()):
            if partial[row] and not np.isnan(g):
                wide.iat[row, int(g)] = np.nan
        G = G + pd.Series(partial.astype(float), index=G.index).where(G.notna())
    period_labels = pd.Series(pd.NaT, index=range(idx.max() + 1))
    period_labels[idx] = labels
    names = {int(g): c for g, c in zip(G, info.cohort) if not np.isnan(g)}
    G.attrs.update(strata=info.stratum.to_numpy(), cohort_names=names,
                   stratify={g for g, c in names.items() if c in stratify})
    return wide, G, period_labels


def to_wide(spec: Spec):
    p = load_long(spec.freq, spec.outcome)
    if spec.start:
        p = p[p.period >= pd.Timestamp(spec.start)]
    if spec.drop_months:
        p = p.assign(y=p.y.where(~p.period.dt.month.isin(spec.drop_months)))
    return build_wide(p, select_units(p, spec), spec.freq, spec.stratify)


# --------------------------------------------------------------------------- 추정

def att_gt(wide: pd.DataFrame, G: pd.Series, base: str, control: str, cycle: int):
    """모든 (g, t) 칸의 ATT와 영향함수 기여 벡터."""
    Y = wide.to_numpy()
    Gv = G.to_numpy()
    n, T = Y.shape
    strata = G.attrs["strata"]
    cells, contrib = [], []
    for g in np.unique(Gv[~np.isnan(Gv)]).astype(int):
        tr_mask = Gv == g
        unit_strata = strata if g in G.attrs["stratify"] else np.zeros(n)
        for t in range(T):
            if base == "universal":
                b = g - 1
            else:
                b = t - cycle * int(np.floor((t - (g - cycle)) / cycle))
            if b < 0 or b >= T or t == b:
                continue
            if control == "never":
                c_mask = np.isnan(Gv)
            else:
                c_mask = np.isnan(Gv) | ((Gv > max(t, b)) & (Gv != g))
            dy = Y[:, t] - Y[:, b]
            valid = ~np.isnan(dy)
            # 층별 비교: 처리 역이 있고 대조 역이 2곳 이상인 층만 쓴다
            parts = []
            for s in np.unique(unit_strata[tr_mask]):
                tr = tr_mask & valid & (unit_strata == s)
                cc = c_mask & valid & (unit_strata == s)
                if tr.sum() and cc.sum() >= 2:
                    parts.append((tr, cc))
            if not parts:
                continue
            n_tr = sum(int(tr.sum()) for tr, _ in parts)
            att, c = 0.0, np.zeros(n)
            for tr, cc in parts:
                w = tr.sum() / n_tr
                mu_g, mu_c = dy[tr].mean(), dy[cc].mean()
                att += w * (mu_g - mu_c)
                c[tr] = w * (dy[tr] - mu_g) / tr.sum()
                c[cc] = -w * (dy[cc] - mu_c) / cc.sum()
            cells.append({"g": g, "t": t, "b": b, "e": t - g, "att": att,
                          "k": int(np.floor((t - (g - cycle)) / cycle)),
                          "n_g": int(tr_mask.sum()), "n_g_valid": n_tr,
                          "n_c": int(sum(cc.sum() for _, cc in parts))})
            contrib.append(c)
    return pd.DataFrame(cells), np.vstack(contrib)


class Aggregator:
    """칸 ATT를 가중 합한 모수와 bootstrap 표준오차. 모든 모수가 같은 ξ를 공유한다
    (역 순서가 같으면 결과변수가 달라도 ξ가 같아 사양 간 차이도 부트스트랩할 수 있다)."""

    def __init__(self, cells: pd.DataFrame, contrib: np.ndarray, seed: int = SEED):
        self.cells = cells.reset_index(drop=True)
        rng = np.random.default_rng(seed)
        xi = rng.choice([-1.0, 1.0], size=(B_BOOT, contrib.shape[1]))
        self.pert = xi @ contrib.T  # B × 칸

    def estimate(self, mask: np.ndarray, by_cohort_size: bool = True) -> tuple[float, float, np.ndarray]:
        w = self.cells.n_g.to_numpy(float) * mask if by_cohort_size else mask.astype(float)
        if w.sum() == 0:
            return np.nan, np.nan, np.full(B_BOOT, np.nan)
        w = w / w.sum()
        draws = self.pert @ w
        return float(self.cells.att.to_numpy() @ w), float(draws.std(ddof=1)), draws


def summarize(agg: Aggregator, labels: pd.Series, G: pd.Series) -> pd.DataFrame:
    c = agg.cells
    t_date = pd.DatetimeIndex(labels.reindex(c.t).to_numpy())
    post = (c.e >= 0).to_numpy()
    names = G.attrs["cohort_names"]
    cohort = c.g.map(names).to_numpy()
    rows = []

    def add(name, mask):
        est, se, _ = agg.estimate(np.asarray(mask))
        rows.append({"param": name, "est": est, "se": se, "lo": est - 1.96 * se, "hi": est + 1.96 * se,
                     "n_cells": int(np.asarray(mask).sum())})

    add("overall_post", post)
    for g in sorted(names):
        add(f"{names[g]}_post", post & (c.g == g).to_numpy())
    c1 = cohort == "C1"
    if c1.any():
        add("C1_pre_kpass(2024-01-27~04-30)", c1 & post & (t_date < KPASS_START))
        for k in (1, 2, 3):
            add(f"C1_year{k}(적용 후 {k}년차)", c1 & post & (c.k == k).to_numpy())
        for year in (2024, 2025, 2026):
            add(f"C1_{year}", c1 & post & (t_date.year == year))
    add("pre_all(placebo)", ~post)
    for g in sorted(names):
        add(f"{names[g]}_pre(placebo)", ~post & (c.g == g).to_numpy())
    return pd.DataFrame(rows)


def event_study(agg: Aggregator, width: int, select: np.ndarray | None = None) -> pd.DataFrame:
    """event time을 width 단위로 묶은 동적 효과. 칸 가중치는 코호트 크기, 동시 신뢰대는 sup-t.
    select로 칸을 제한하면(예: 한 코호트) 그 칸들만 집계한다."""
    c = agg.cells
    keep = np.ones(len(c), bool) if select is None else np.asarray(select)
    c_bin = np.floor(c.e / width).astype(int).to_numpy()
    rows, draws = [], []
    for k in np.unique(c_bin[keep]):
        est, se, d = agg.estimate((c_bin == k) & keep)
        rows.append({"bin": int(k), "e_start": int(k * width), "est": est, "se": se,
                     "n_cells": int(((c_bin == k) & keep).sum())})
        draws.append(d)
    out = pd.DataFrame(rows)
    D = np.column_stack(draws)
    se = out.se.to_numpy()
    tmax = np.nanmax(np.abs((D - D.mean(axis=0)) / se), axis=1)
    crit = float(np.quantile(tmax, 0.95))
    out["lo"], out["hi"] = out.est - 1.96 * out.se, out.est + 1.96 * out.se
    out["lo_unif"], out["hi_unif"] = out.est - crit * out.se, out.est + crit * out.se
    return out


def fit(spec: Spec):
    """사양 하나를 추정해 (칸, Aggregator, G, 기간 라벨)을 돌려준다."""
    wide, G, labels = to_wide(spec)
    cycle = 52 if spec.freq == "week" else 12
    cells, contrib = att_gt(wide, G, spec.base, spec.control, cycle)
    return cells, Aggregator(cells, contrib), G, labels


def run(spec: Spec) -> dict:
    cells, agg, G, labels = fit(spec)
    summary = summarize(agg, labels, G)
    event = event_study(agg, width=4 if spec.freq == "week" else 1)
    cells["t_label"] = labels.reindex(cells.t).to_numpy()
    cells["cohort"] = cells.g.map(G.attrs["cohort_names"])
    OUT_TABLES.mkdir(parents=True, exist_ok=True)
    cells.to_csv(OUT_TABLES / f"cs_{spec.name}_cells.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(OUT_TABLES / f"cs_{spec.name}_summary.csv", index=False, encoding="utf-8-sig")
    event.to_csv(OUT_TABLES / f"cs_{spec.name}_event.csv", index=False, encoding="utf-8-sig")
    counts = {name: int((G == g).sum()) for g, name in G.attrs["cohort_names"].items()}
    counts["NT"] = int(G.isna().sum())
    return {"spec": spec, "summary": summary, "event": event, "agg": agg, "G": G,
            "labels": labels, "n_units": counts}


# --------------------------------------------------------------------------- 진단·민감도

def covid_baseline() -> pd.DataFrame:
    """2019(코로나 전) 대비 처리 − 대조 log 승차 격차의 연도별 변화.
    역별로 연 일평균 승차 log의 2019 대비 변화를 구해 처리·대조 평균 차이를 낸다(층화 그룹은 층 안에서).
    2026은 1~8월을 2019년 1~8월과 비교한다. 모든 해에 월 자료가 빠짐없는 역만 쓴다."""
    p = pd.read_parquet(DATA_PROCESSED / "panel_month.parquet")
    p["year"], p["mm"] = p.month.dt.year, p.month.dt.month
    full = {2019: 12, 2022: 12, 2023: 12, 2024: 12, 2025: 12}

    def level(df: pd.DataFrame, months: range) -> pd.Series:
        x = df[df.mm.isin(months)]
        g = x.groupby("complex").agg(on=("on", "sum"), days=("days", "sum"), n=("mm", "nunique"))
        return np.log(g.on / g.days).where(g.n == len(months))

    lv = {y: level(p[p.year == y], range(1, 13)) for y in full}
    lv["2026(1~8월)"] = level(p[p.year == 2026], range(1, 9))
    base_ja = level(p[p.year == 2019], range(1, 9))
    delta = pd.DataFrame({y: lv[y] - (base_ja if y == "2026(1~8월)" else lv[2019]) for y in lv}).dropna()

    units = select_units(p, aprime("diag", cohorts=("C1", "C5")))
    all_units = select_units(p, Spec("diag_all", cohorts=("C1", "C5"), strata="am_quartile"))
    groups = {
        "A′: C1(업무·관광형 제외) − 통근권 대조, 층화": (units, "C1", True),
        "C1 전체 − 통근권 대조(무층화)": (all_units, "C1", False),
        "C1 업무·관광형(Q1) − 대조 Q1": (all_units[all_units.stratum == "Q1_업무관광"], "C1", False),
        "C5 성남 − 통근권 대조(무층화)": (all_units, "C5", False),
    }
    rows = []
    for name, (u, coh, stratified) in groups.items():
        d = delta.join(u[["cohort", "stratum"]], how="inner")
        tr, cc = d[d.cohort == coh], d[d.cohort == "NT"]
        strata = tr.stratum.unique() if stratified else [None]
        for y in lv:
            est, var, n_t = 0.0, 0.0, len(tr)
            for s in strata:
                a = tr if s is None else tr[tr.stratum == s]
                b = cc if s is None else cc[cc.stratum == s]
                w = len(a) / n_t
                est += w * (a[y].mean() - b[y].mean())
                var += w**2 * (a[y].var(ddof=1) / len(a) + b[y].var(ddof=1) / len(b))
            rows.append({"group": name, "year": str(y), "gap_vs_2019": est, "se": np.sqrt(var),
                         "n_treated": n_t, "n_control": len(cc)})
    return pd.DataFrame(rows)


def honest_rm(res: dict, benchmarks: dict[str, float | str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """C1에 대한 Δ^RM 민감도. benchmarks: 이름 → 고정 D(연간, float) 또는 날짜 문자열 —
    그 날짜 이후의 사전 칸(k=−1, 기준 연도 한 해 전) 평균의 |값|을 부트스트랩과 함께 D로 쓴다.
    반환: (M 격자 표, 붕괴점 표)."""
    agg, G = res["agg"], res["G"]
    c = agg.cells
    g1 = next(g for g, name in G.attrs["cohort_names"].items() if name == "C1")
    sel = (c.g == g1).to_numpy()
    k = c.k.to_numpy()
    t_date = pd.DatetimeIndex(res["labels"].reindex(c.t).to_numpy())
    targets = {f"{kk}년차": sel & (k == kk) for kk in (1, 2, 3)}
    targets["적용 후 전체"] = sel & (k >= 1)
    rows, breaks = [], []
    for bname, bench in benchmarks.items():
        if isinstance(bench, str):
            pre_est, _, pre_draws = agg.estimate(sel & (k == -1) & (t_date >= pd.Timestamp(bench)),
                                                 by_cohort_size=False)
            D, D_draws = abs(pre_est), np.abs(pre_est + pre_draws)
        else:
            D, D_draws = bench, np.full(B_BOOT, bench)
        for tname, mask in targets.items():
            est, se, draws = agg.estimate(mask, by_cohort_size=False)
            k_eff = float(k[mask].mean())

            def band(mbar):
                lo_d = est + draws - k_eff * mbar * D_draws
                hi_d = est + draws + k_eff * mbar * D_draws
                return (est - k_eff * mbar * D, est + k_eff * mbar * D,
                        float(np.quantile(lo_d, 0.025)), float(np.quantile(hi_d, 0.975)))

            for mbar in MBARS:
                id_lo, id_hi, ci_lo, ci_hi = band(mbar)
                rows.append({"benchmark": bname, "D_annual": D, "target": tname, "k_mean": k_eff,
                             "Mbar": mbar, "est": est, "se": se, "id_lo": id_lo, "id_hi": id_hi,
                             "ci_lo": ci_lo, "ci_hi": ci_hi})
            grid = np.round(np.arange(0, 5.001, 0.05), 2)
            covers = [m for m in grid if band(m)[2] <= 0 <= band(m)[3]]
            breaks.append({"benchmark": bname, "target": tname, "est": est,
                           "breakdown_Mbar": covers[0] if covers else np.nan})
    return pd.DataFrame(rows), pd.DataFrame(breaks)


# --------------------------------------------------------------------------- 실행

SPECS = [
    aprime("Aprime_week"),                                            # 주 사양
    aprime("Aprime_month_2022", freq="month", start="2022-01-01"),    # 2022 포함 — C1 사전추세·HonestDiD
    aprime("Aprime_month_2022_noholiday", freq="month", start="2022-01-01",
           drop_months=HOLIDAY_MONTHS),                               # 설·추석 달 제외(해마다 달이 바뀜)
    aprime("Aprime_week_fullctrl", controls="full"),                  # 전체 대조군(행락형 포함)
    aprime("Aprime_week_notyet", control="notyet"),                   # not-yet-treated 포함
    aprime("Aprime_week_withring2", controls="with_ring2"),          # 이전 기준: 경계 2차 링을 대조에 포함
    Spec("C6_aux_week", cohorts=("C6",)),                             # 보조: 하남(수요 정착 추세)
    Spec("C4_gwacheon_case", cohorts=("C4",), c4_units=GWACHEON),     # 사례: 과천역 1곳(SE 무효)
    Spec("uncond_week"),                                              # 비교용: 조건 없는 원 사양
    Spec("uncond_month_2022", freq="month", start="2022-01-01"),
    Spec("week_universal", base="universal"),                        # 비교용: 계절 조정 없음(처리 직전 주 기준)
]
PREVIEW_SPECS = [
    Spec("preview_week_strata4", strata="am_quartile", stratify=TREATED_COHORTS),
    Spec("preview_month_strata4_2022", freq="month", start="2022-01-01", strata="am_quartile",
         stratify=TREATED_COHORTS),
    Spec("preview_week_strata3", strata="am_quartile", stratify=TREATED_COHORTS, drop_strata=("Q1_업무관광",)),
    Spec("preview_month_strata3_2022", freq="month", start="2022-01-01", strata="am_quartile",
         stratify=TREATED_COHORTS, drop_strata=("Q1_업무관광",)),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", action="store_true", help="층화 미리보기 사양만 실행")
    args = ap.parse_args()
    pd.set_option("display.width", 200)
    results = {}
    for spec in PREVIEW_SPECS if args.preview else SPECS:
        res = run(spec)
        results[spec.name] = res
        print(f"\n=== {spec.name} {res['n_units']} ===")
        print(res["summary"].round(4).to_string(index=False))
    if args.preview:
        return

    base = covid_baseline()
    base.to_csv(OUT_TABLES / "diag_2019_baseline.csv", index=False, encoding="utf-8-sig")
    print("\n=== 2019 대비 처리 − 대조 log 승차 격차 변화(%) ===")
    print((base.assign(gap=100 * base.gap_vs_2019, se=100 * base.se)
           .pivot(index="year", columns="group", values="gap")).round(2).to_string())

    a = base[base.group.str.startswith("A′")].set_index("year").gap_vs_2019
    structural = abs(a["2023"]) / 4  # 2019→2023 4년간 구조 변화를 연 단위로
    benchmarks = {"2022→2023 사전 추세(2022 전체)": "2022-01-01",
                  "2022→2023 사전 추세(거리두기 해제 뒤 2022-05~)": "2022-05-01",
                  "2019→2023 구조 추세(연환산)": structural}
    for spec_name, suffix in (("Aprime_week", ""), ("Aprime_month_2022", "_month")):
        grid, breaks = honest_rm(results[spec_name], benchmarks)
        grid.to_csv(OUT_TABLES / f"honest_rm{suffix}.csv", index=False, encoding="utf-8-sig")
        breaks.to_csv(OUT_TABLES / f"honest_rm{suffix}_breakdown.csv", index=False, encoding="utf-8-sig")
        print(f"\n=== HonestDiD 상대적 크기 제약, C1 ({spec_name}) ===")
        show = grid[grid.target.isin(["1년차", "2년차", "적용 후 전체"]) & grid.Mbar.isin([0, 1, 2])].copy()
        for col in ["D_annual", "est", "id_lo", "id_hi", "ci_lo", "ci_hi"]:
            show[col] = (100 * show[col]).round(2)
        print(show.drop(columns=["se", "k_mean"]).to_string(index=False))


if __name__ == "__main__":
    main()
