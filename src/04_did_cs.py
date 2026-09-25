"""Callaway & Sant'Anna(2021) staggered DiD — 공변량 없음, 물리적 역 단위.

ATT(g,t) = E[Y_t − Y_b | G=g] − E[Y_t − Y_b | C]
- Y: log(주간 승차) 또는 log(월 일평균 승차)
- C: never-treated(주), 선택 시 + not-yet-treated(G > max(t, b))
- 기준기간 b
    universal  b = g − 1 (처리 직전 기간) — 표준 event-study
    seasonal   b = 처리 직전 한 주기(52주/12개월) 안의 같은 주차·월 → 전년 동기 대비.
               역별 계절성을 없앤다. 처리 직전 한 주기 안의 t는 b = t라 정의상 0이다.
추론: 역 단위 multiplier bootstrap(영향함수, Rademacher, B=999). 역이 곧 클러스터다.
설·추석 연휴가 낀 주는 결측으로 둔다.
층화(strata): 역 유형 안에서만 처리·대조를 비교하고 처리 역 수로 가중해 합친다
(이산 공변량을 포화시킨 CS outcome regression과 같다) — 조건부 평행추세.

사용 예
  python src/04_did_cs.py                  # 주 추정 사양 전체 실행
출력 outputs/tables/cs_{spec}_cells.csv · cs_{spec}_summary.csv · cs_{spec}_event.csv
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from common import DATA_PROCESSED, OUT_TABLES

TREATED_COHORTS = ["C1", "C4", "C5", "C6"]
KPASS_START = pd.Timestamp("2024-05-01")
B_BOOT = 999
SEED = 20260925


@dataclass
class Spec:
    name: str
    freq: str = "week"          # week | month
    base: str = "seasonal"      # seasonal | universal
    control: str = "never"      # never | notyet
    controls: str = "main"      # main(통근권) | full(행락형 포함)
    start: str | None = None    # 추정 표본 시작(예: '2023-01-01')
    strata: str | None = None   # 층화 기준: 'am_quartile'(2023년 07~09시 승차 비중 사분위)
    drop_strata: tuple = ()     # 대조 역이 부족해 뺄 층


def station_strata(kind: str, units: pd.Index) -> pd.Series:
    """사전기간(2023) 시간대 프로필로 정한 역 유형. 사분위 경계는 추정 표본 역 기준."""
    prof = pd.read_parquet(DATA_PROCESSED / "station_profile_2023.parquet").set_index("complex").loc[units]
    if kind == "am_quartile":
        am = prof.h7 + prof.h8
        return pd.qcut(am, 4, labels=["Q1_업무관광", "Q2", "Q3", "Q4_주거"]).astype(str)
    raise ValueError(kind)


def select_units(panel: pd.DataFrame, controls: str) -> pd.DataFrame:
    """주 표본 처리 역 + 대조 역. controls='full'이면 행락형(leisure)만 걸린 NT 역도 넣는다."""
    reason = panel.exclude_reason.fillna("")
    treated = panel.cohort.isin(TREATED_COHORTS) & (reason == "")
    ok_ctrl = {"main": [""], "full": ["", "leisure"]}[controls]
    control = (panel.cohort == "NT") & reason.isin(ok_ctrl)
    return panel[treated | control]


def to_wide(spec: Spec) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """log 결과변수 행렬(역 × 기간 정수 인덱스), 처리 기간 인덱스 G(NT는 NaN), 기간 라벨.
    층화 사양이면 G.attrs['strata']에 역별 층을 담는다."""
    if spec.freq == "week":
        p = pd.read_parquet(DATA_PROCESSED / "panel_week.parquet")
        p["y"] = np.log(p.on.where(p.on > 0)).where(~p.holiday_week)
        p["period"] = p.week
    else:
        p = pd.read_parquet(DATA_PROCESSED / "panel_month.parquet")
        p["y"] = np.log((p.on / p.days).where(p.on > 0))
        p["period"] = p.month
    if spec.start:
        p = p[p.period >= pd.Timestamp(spec.start)]
    p = select_units(p, spec.controls)
    strata = None
    if spec.strata:
        strata = station_strata(spec.strata, pd.Index(p.complex.unique()))
        strata = strata[~strata.isin(spec.drop_strata)]
        p = p[p.complex.isin(strata.index)]
    labels = pd.Index(sorted(p.period.unique()))
    if spec.freq == "week":
        idx = ((labels - labels[0]).days // 7).astype(int)
        g_idx = lambda d: (d - labels[0]).days // 7  # noqa: E731
    else:
        idx = (labels.year * 12 + labels.month - (labels[0].year * 12 + labels[0].month)).astype(int)
        g_idx = lambda d: (d.year * 12 + d.month) - (labels[0].year * 12 + labels[0].month)  # noqa: E731
    wide = p.pivot_table(index="complex", columns="period", values="y")
    wide.columns = pd.Index(idx[labels.get_indexer(wide.columns)])
    wide = wide.reindex(columns=range(idx.max() + 1))
    info = p.drop_duplicates("complex").set_index("complex").loc[wide.index]
    G = info.treat_date.map(lambda d: g_idx(d) if pd.notna(d) else np.nan).astype(float)
    # 월 단위에서 처리일이 월 중간이면 그 달은 부분 처리 → 처리 역의 그 달을 결측으로 두고 다음 달을 첫 처리 기간으로 본다
    if spec.freq == "month":
        partial = (info.treat_date.dt.day > 1).to_numpy()
        for row, g in enumerate(G.to_numpy()):
            if partial[row] and not np.isnan(g):
                wide.iat[row, int(g)] = np.nan
        G = G + pd.Series(partial.astype(float), index=G.index).where(G.notna())
    period_labels = pd.Series(pd.NaT, index=range(idx.max() + 1))
    period_labels[idx] = labels
    if strata is not None:
        G.attrs["strata"] = strata.loc[wide.index].to_numpy()
    # 코호트 이름은 순서가 아니라 역의 코호트 값으로 붙인다(층을 빼면 코호트가 통째로 빠질 수 있음)
    G.attrs["cohort_names"] = {int(g): name for g, name in zip(G, info.cohort) if not np.isnan(g)}
    return wide, G, period_labels


def att_gt(wide: pd.DataFrame, G: pd.Series, base: str, control: str, cycle: int):
    """모든 (g, t) 칸의 ATT와 영향함수 기여 벡터. G.attrs['strata']가 있으면 층 안에서만 비교."""
    Y = wide.to_numpy()
    Gv = G.to_numpy()
    n, T = Y.shape
    strata = G.attrs.get("strata", np.zeros(n))
    cells, contrib = [], []
    for g in np.unique(Gv[~np.isnan(Gv)]).astype(int):
        tr_mask = Gv == g
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
            for s in np.unique(strata[tr_mask]):
                tr = tr_mask & valid & (strata == s)
                cc = c_mask & valid & (strata == s)
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
                          "n_g": int(tr_mask.sum()), "n_g_valid": n_tr,
                          "n_c": int(sum(cc.sum() for _, cc in parts))})
            contrib.append(c)
    return pd.DataFrame(cells), np.vstack(contrib)


class Aggregator:
    """칸 ATT를 가중 합한 모수와 bootstrap 표준오차. 모든 모수가 같은 ξ를 공유한다."""

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


def summarize(agg: Aggregator, labels: pd.Series, G: pd.Series, freq: str) -> pd.DataFrame:
    c = agg.cells
    t_date = labels.reindex(c.t).to_numpy()
    post = (c.e >= 0).to_numpy()
    rows = []

    def add(name, mask):
        est, se, _ = agg.estimate(np.asarray(mask))
        rows.append({"param": name, "est": est, "se": se, "lo": est - 1.96 * se, "hi": est + 1.96 * se,
                     "n_cells": int(np.asarray(mask).sum())})

    add("overall_post", post)
    cohort_of = G.attrs["cohort_names"]
    for g in sorted(cohort_of):
        add(f"{cohort_of[g]}_post", post & (c.g == g).to_numpy())
    c1 = (c.g.map(cohort_of) == "C1").to_numpy()
    add("C1_pre_kpass(2024-01-27~04-30)", c1 & post & (t_date < np.datetime64(KPASS_START)))
    for year in [2024, 2025, 2026]:
        add(f"C1_{year}", c1 & post & (pd.DatetimeIndex(t_date).year == year))
    add("pre_all(placebo)", ~post & (c.e < 0).to_numpy())
    for g in sorted(cohort_of):
        add(f"{cohort_of[g]}_pre(placebo)", ~post & (c.g == g).to_numpy())
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
    out.attrs["crit"] = crit
    return out


def run(spec: Spec) -> dict:
    wide, G, labels = to_wide(spec)
    cycle = 52 if spec.freq == "week" else 12
    cells, contrib = att_gt(wide, G, spec.base, spec.control, cycle)
    agg = Aggregator(cells, contrib)
    summary = summarize(agg, labels, G, spec.freq)
    event = event_study(agg, width=4 if spec.freq == "week" else 1)
    cells["t_label"] = labels.reindex(cells.t).to_numpy()
    cells["cohort"] = cells.g.map(G.attrs["cohort_names"])
    OUT_TABLES.mkdir(parents=True, exist_ok=True)
    cells.to_csv(OUT_TABLES / f"cs_{spec.name}_cells.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(OUT_TABLES / f"cs_{spec.name}_summary.csv", index=False, encoding="utf-8-sig")
    event.to_csv(OUT_TABLES / f"cs_{spec.name}_event.csv", index=False, encoding="utf-8-sig")
    n_units = pd.Series(G.isna()).map({True: "NT", False: "treated"}).value_counts().to_dict()
    return {"spec": spec, "summary": summary, "event": event, "n_units": n_units}


SPECS = [
    Spec("week_seasonal"),                                   # 주 추정
    Spec("week_universal", base="universal"),                # 계절 조정 없음(비교용)
    Spec("month_seasonal_2022", freq="month"),               # 2022 포함: C1 사전추세 검정
    Spec("week_seasonal_fullctrl", controls="full"),         # 전체 대조군
    Spec("week_seasonal_notyet", control="notyet"),          # not-yet-treated 포함
]
# 결정 필요 3(A안) 미리보기 — 채택 전
PREVIEW_SPECS = [
    Spec("preview_week_strata4", strata="am_quartile"),
    Spec("preview_month_strata4_2022", freq="month", strata="am_quartile"),
    Spec("preview_week_strata3", strata="am_quartile", drop_strata=("Q1_업무관광",)),
    Spec("preview_month_strata3_2022", freq="month", strata="am_quartile", drop_strata=("Q1_업무관광",)),
]


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", action="store_true", help="결정 전 미리보기 사양만 실행")
    args = ap.parse_args()
    pd.set_option("display.width", 200)
    for spec in PREVIEW_SPECS if args.preview else SPECS:
        res = run(spec)
        print(f"\n=== {spec.name} ({res['n_units']}) ===")
        print(res["summary"].round(4).to_string(index=False))


if __name__ == "__main__":
    main()
