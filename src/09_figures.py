"""보고서 그림 4장 (본문 상한). A4 본문 폭(6.7in)에 맞춰 그리고, 그림 번호·설명은 보고서 캡션에 둔다.

fig1_timeline_map.png  적용 타임라인 + 역 지도(분석 적용 역·경계 바깥 1차 링·통근권 대조)
fig2_event_study.png   주 사양 A′ event-study: C1(주, 4주 묶음, 2022 사전 포함)·C5
fig3_boundary.png      경계: 거리 기울기(승차·하차) · 서울 버스 도달별 비교 · 1차 링 월 event-study
fig4_carbon.png        탄소 범위(승용차 대체 비율별) vs 서울시 발표, 경계 역효과 가능 범위
입력은 04·06·07·08이 만든 outputs/tables/*.csv와 04의 추정 함수. 값은 표에 있으므로 그림에는 숫자를 최소로 단다.
"""
from __future__ import annotations

import importlib.util
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.ticker  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from common import DATA_REFERENCE, OUT_FIGURES, OUT_TABLES, ROOT  # noqa: E402


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "src" / file)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


did = _load("did_cs", "04_did_cs.py")
het = _load("heterogeneity", "06_heterogeneity.py")
bus = _load("bus_substitution", "07_bus_substitution.py")

W = 6.7                                   # A4 본문 폭(in)
FS, FS_S, FS_T = 6.4, 5.8, 7.6            # 본문·작은 글씨·패널 제목(pt, 인쇄 크기 그대로)
INK, INK2, MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, BASELINE, SURFACE, SHADE = "#e1e0d9", "#c3c2b7", "#fcfcfb", "#f0efec"
BLUE, ORANGE, AQUA, GRAY = "#2a78d6", "#eb6834", "#1baf7a", "#c9c8c2"  # 범주 3색(전 쌍 검증 통과) + 회색
C1_START = pd.Timestamp("2024-01-27")


def style(ax, grid_axis="y") -> None:
    ax.set_facecolor(SURFACE)
    ax.grid(axis=grid_axis, color=GRID, lw=0.6)
    ax.tick_params(colors=MUTED, labelsize=FS_S, length=0, pad=2)
    for side in ["top", "right", "left"]:
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(BASELINE)
    ax.spines["bottom"].set_linewidth(0.7)


def title(ax, text) -> None:
    ax.set_title(text, fontsize=FS_T, color=INK, loc="left", pad=4)


def save(fig, name: str) -> None:
    OUT_FIGURES.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_FIGURES / name, dpi=300, facecolor=SURFACE)
    plt.close(fig)
    print(f"저장: {OUT_FIGURES / name}")


# --------------------------------------------------------------------------- 그림 1

LABEL_OFFSETS = {  # 1차 링 역 이름 위치(점 단위 오프셋, 정렬) — 가까운 역끼리 겹치지 않게
    "회룡": (5, 0, "left"), "망월사": (-5, 0, "right"), "석수": (4, 1, "left"), "관악": (4, -5, "left"),
    "광명": (-4, -6, "right"), "역곡": (1, 4, "left"), "소사": (-4, -4, "right"), "검암": (0, 4, "center"),
}


def fig1() -> None:
    fig = plt.figure(figsize=(W, 2.75), facecolor=SURFACE, layout="constrained")
    gs = fig.add_gridspec(1, 2, width_ratios=[1.55, 1])
    ax_t, ax_m = fig.add_subplot(gs[0]), fig.add_subplot(gs[1])

    # 타임라인 — (라벨, 날짜, 데이터 포함, 위(+1)/아래(-1))
    style(ax_t, grid_axis="x")
    rows = {"적용 확대": 2, "카드 제도": 1, "교란 사건": 0}
    cohorts = [("C1 서울", "2024-01-27", True, 1), ("C2 김포*", "2024-03-30", False, -1),
               ("C3 남양주*", "2024-08-10", False, 1), ("C4 고양·과천", "2024-11-30", True, -1),
               ("C5 성남", "2025-05-03", True, 1), ("C6 하남", "2025-08-09", True, -1)]
    policy = [("본사업·청년할인", "2024-07-01", 1), ("후불카드", "2024-11-30", -1)]
    confound = [("요금 인상", "2023-10-07", 1), ("GTX-A", "2024-03-30", -1), ("K-패스", "2024-05-01", 1),
                ("별내선", "2024-08-10", -1), ("GTX-A", "2024-12-28", 1), ("요금 인상·인천1 검단", "2025-06-28", -1)]

    def label(x, y, text, side, color, fs=FS):
        ax_t.text(x, y + 0.17 * side, text, ha="center", va="bottom" if side > 0 else "top", fontsize=fs, color=color)

    for lab, d, in_data, side in cohorts:
        x = pd.Timestamp(d)
        ax_t.plot(x, rows["적용 확대"], "o", ms=5, color=BLUE if in_data else SURFACE, mec=BLUE, mew=1.2, zorder=3)
        label(x, rows["적용 확대"], lab, side, INK)
    for lab, d, side in policy:
        ax_t.plot(pd.Timestamp(d), rows["카드 제도"], "s", ms=4.2, color=INK2, zorder=3)
        label(pd.Timestamp(d), rows["카드 제도"], lab, side, INK2)
    for lab, d, side in confound:
        ax_t.plot(pd.Timestamp(d), rows["교란 사건"], "D", ms=3.4, color=MUTED, zorder=3)
        label(pd.Timestamp(d), rows["교란 사건"], lab, side, MUTED, FS_S)
    x0 = pd.Timestamp("2023-07-01")
    ax_t.axvspan(x0, C1_START, color=SHADE, lw=0, zorder=0)
    ax_t.text(x0 + pd.Timedelta(days=10), 2.72, "← 사전기간(2022-01~)", fontsize=FS_S, color=MUTED, va="center")
    ax_t.set_yticks(list(rows.values()), list(rows.keys()), fontsize=FS, color=INK2)
    ax_t.set_ylim(-0.75, 2.95)
    ax_t.set_xlim(x0, pd.Timestamp("2026-09-30"))
    ticks = pd.to_datetime(["2024-01-01", "2024-07-01", "2025-01-01", "2025-07-01", "2026-01-01", "2026-07-01"])
    ax_t.set_xticks(ticks, [f"{t.year}.{t.month}" for t in ticks])
    title(ax_t, "적용 확대와 주요 사건 (* = 데이터셋 미포함)")

    # 지도
    coords = bus.station_coords()
    cmap = pd.read_csv(DATA_REFERENCE / "cohort_map.csv", dtype=str, keep_default_na=False)
    cx = cmap[cmap.in_data == "Y"].groupby("complex").agg(cohort=("cohort", "first")).join(coords, how="inner")
    units = did.select_units(did.load_long("week", "on"), did.aprime("fig"))
    analysed = set(units.index[units.cohort.isin(["C1", "C5"])])
    control = set(units.index[units.cohort == "NT"])
    ring1 = set(het.RING1)
    cat = np.where(cx.index.isin(ring1), "ring1", np.where(cx.index.isin(analysed), "treat",
                                                           np.where(cx.index.isin(control), "ctrl", "other")))
    style(ax_m, grid_axis="both")
    ax_m.grid(False)
    for key, color, size, lab in (("other", GRAY, 3, "그 밖(제외 역)"),
                                  ("ctrl", AQUA, 5, f"통근권 대조 역({len(control)})"),
                                  ("treat", BLUE, 5, f"분석한 적용 역({len(analysed)})"),
                                  ("ring1", ORANGE, 17, "경계 바깥 1차 링(8)")):
        m = cat == key
        ax_m.scatter(cx.lon[m], cx.lat[m], s=size, color=color, edgecolor=SURFACE, lw=0.3, label=lab, zorder=3)
    for s, (dx, dy, ha) in LABEL_OFFSETS.items():
        if s in cx.index:
            ax_m.annotate(s, (cx.at[s, "lon"], cx.at[s, "lat"]), xytext=(dx, dy), textcoords="offset points",
                          fontsize=FS_S, color=INK, ha=ha, va="center" if dy == 0 else "bottom" if dy > 0 else "top")
    ax_m.set_xlim(126.62, 127.30)
    ax_m.set_ylim(37.33, 37.80)
    ax_m.set_aspect(1 / np.cos(np.radians(37.55)))
    ax_m.set_anchor("N")
    ax_m.set_xticks([])
    ax_m.set_yticks([])
    ax_m.spines["bottom"].set_visible(False)
    ax_m.legend(loc="upper center", bbox_to_anchor=(0.5, 0.0), ncol=2, fontsize=FS_S, frameon=False,
                labelcolor=INK2, handletextpad=0.1, columnspacing=0.6, borderaxespad=0.2, markerscale=1.2)
    title(ax_m, "역 구분 (서울과 주변)")
    save(fig, "fig1_timeline_map.png")


# --------------------------------------------------------------------------- 그림 2

def cohort_event(spec, width) -> pd.DataFrame:
    cells, agg, G, labels = did.fit(spec)
    out = []
    for g, name in G.attrs["cohort_names"].items():
        ev = did.event_study(agg, width, select=(cells.g == g).to_numpy())
        ev["cohort"], ev["n"] = name, int((G == g).sum())
        out.append(ev)
    return pd.concat(out, ignore_index=True)


def draw_event(ax, ev, text, cycle, xlabel, marks=(), color=BLUE) -> None:
    style(ax)
    ax.axvspan(-cycle, 0, color=SHADE, lw=0, zorder=0)
    ax.text(-cycle / 2, 0.97, "기준 연도\n(정의상 0)", transform=ax.get_xaxis_transform(), ha="center", va="top",
            fontsize=FS_S, color=MUTED, linespacing=1.1)
    ax.axhline(0, color=BASELINE, lw=0.8, zorder=1)
    ax.axvline(0, color=MUTED, lw=0.8, zorder=1)
    for i, (x, lab) in enumerate(marks):
        ax.axvline(x, color=MUTED, lw=0.6, ls=(0, (2, 2)), zorder=1)
        ax.text(x + cycle * 0.012, 0.97 - 0.09 * (i % 2), lab, transform=ax.get_xaxis_transform(), va="top",
                fontsize=FS_S, color=INK2)
    ax.vlines(ev.e_start, 100 * ev.lo, 100 * ev.hi, color=color, lw=0.9, alpha=0.45, zorder=2)
    ax.plot(ev.e_start, 100 * ev.est, "o", ms=2.8, color=color, mec=SURFACE, mew=0.6, zorder=3)
    title(ax, text)
    ax.set_xlabel(xlabel, fontsize=FS, color=INK2, labelpad=2)


def fig2() -> None:
    ev = cohort_event(did.aprime("fig2"), 4)
    fig, axes = plt.subplots(1, 2, figsize=(W, 2.2), facecolor=SURFACE, layout="constrained",
                             gridspec_kw={"width_ratios": [1.6, 1]})
    c1 = ev[ev.cohort == "C1"]
    kp = (pd.Timestamp("2024-05-01") - C1_START).days / 7
    hb = (pd.Timestamp("2024-11-30") - C1_START).days / 7
    draw_event(axes[0], c1, f"C1 서울 비도심 {int(c1.n.iloc[0])}역 (4주 묶음)", 52, "적용 후 주",
               marks=((kp, "K-패스"), (hb, "후불카드")))
    c5 = ev[ev.cohort == "C5"]
    draw_event(axes[1], c5, f"C5 성남 {int(c5.n.iloc[0])}역 (4주 묶음)", 52, "적용 후 주")
    axes[0].set_ylabel("처리 - 대조 (%)", fontsize=FS, color=INK2, labelpad=2)
    save(fig, "fig2_event_study.png")


# --------------------------------------------------------------------------- 그림 3

def dot_rows(ax, rows, text) -> None:
    """rows: [(라벨, 추정, SE, 색)] — 가로 점·95% 신뢰구간."""
    style(ax, grid_axis="x")
    for i, (lab, est, se, color) in enumerate(rows):
        y = len(rows) - 1 - i
        ax.hlines(y, 100 * (est - 1.96 * se), 100 * (est + 1.96 * se), color=color, lw=1.6, alpha=0.5)
        ax.plot(100 * est, y, "o", ms=4, color=color, mec=SURFACE, mew=0.8, zorder=3)
        ax.annotate(f"{100 * est:+.1f}%", (100 * (est + 1.96 * se), y), xytext=(3, 0), textcoords="offset points",
                    va="center", fontsize=FS_S, color=INK2)
    ax.axvline(0, color=BASELINE, lw=0.8)
    ax.set_yticks(range(len(rows)), [r[0] for r in rows][::-1], fontsize=FS, color=INK2)
    ax.set_ylim(-0.6, len(rows) - 0.4)
    title(ax, text)
    ax.set_xlabel("처리 - 대조 (%)", fontsize=FS, color=INK2, labelpad=2)


def fig3() -> None:
    s = pd.read_csv(OUT_TABLES / "cs_Aprime_week_summary.csv").set_index("param")
    al = pd.read_csv(OUT_TABLES / "ring_alighting.csv")
    b = pd.read_csv(OUT_TABLES / "boundary_absorption.csv")
    reach = pd.read_csv(OUT_TABLES / "bus_subway_by_reach.csv").set_index("group")

    def pick(group, outcome):
        r = al[(al.group == group) & (al.outcome == outcome) & (al.window == "노출 후 전체")].iloc[0]
        return r.est, r.se

    inn = b[(b.group.str.startswith("안쪽·해소 없음")) & (b.freq == "week") & (b.window == "노출 후 전체")].iloc[0]
    fig = plt.figure(figsize=(W, 3.85), facecolor=SURFACE, layout="constrained")
    gs = fig.add_gridspec(2, 2, height_ratios=[1, 1.1], width_ratios=[1.3, 1])
    ax1, ax3, ax2 = fig.add_subplot(gs[0, 0]), fig.add_subplot(gs[0, 1]), fig.add_subplot(gs[1, :])
    rows = [("서울 안 적용 역(A′) 승차", s.at["C1_post", "est"], s.at["C1_post", "se"], BLUE),
            ("서울 쪽 경계역 승차", inn.est, inn.se, BLUE),
            ("경계 바깥 1차 링 승차", *pick("1차 링", "승차"), ORANGE),
            ("경계 바깥 1차 링 하차", *pick("1차 링", "하차"), ORANGE),
            ("경계 바깥 2차 링 승차", *pick("2차 링", "승차"), AQUA)]
    dot_rows(ax1, rows, "① 경계에서 멀어질수록 약해지는 이탈")
    r_in, r_out = reach.loc["1차 링·닿음"], reach.loc["1차 링·안 닿음"]
    d = reach.loc["1차 링: 닿음 − 안 닿음"]
    dot_rows(ax3, [(f"서울 버스 닿는 역({r_in.n:.0f})", r_in.est, r_in.se, ORANGE),
                   (f"서울 버스 안 닿는 역({r_out.n:.0f})", r_out.est, r_out.se, GRAY)],
             "③ 1차 링 이탈: 서울 버스 도달별")
    ax3.text(0.02, 0.5, f"차이 {100 * d.est:+.1f}%p (SE {100 * d.se:.1f})", transform=ax3.transAxes,
             fontsize=FS_S, color=INK2, va="center")
    ev = pd.read_csv(OUT_TABLES / "ring_event_month.csv")
    r1 = ev[ev.group == "1차 링"]
    draw_event(ax2, r1, "② 경계 바깥 1차 링 8역, 월별 (2022 사전 포함)", 12, "적용 후 개월",
               marks=((5, "본사업"), (10, "후불카드"), (17, "인천1 검단연장")), color=ORANGE)
    ax2.set_ylabel("처리 - 대조 (%)", fontsize=FS, color=INK2, labelpad=2)
    save(fig, "fig3_boundary.png")


# --------------------------------------------------------------------------- 그림 4

def fig4() -> None:
    rng = pd.read_csv(OUT_TABLES / "carbon_range.csv")
    bnd = pd.read_csv(OUT_TABLES / "carbon_boundary.csv")
    fig, ax = plt.subplots(figsize=(W, 2.25), facecolor=SURFACE, layout="constrained")
    style(ax, grid_axis="x")
    shares = [("서울시 설문 4%", "승용차 대체 4%(서울시 설문)"), ("25%", "승용차 대체 25%"),
              ("100%(극단)", "승용차 대체 100%(극단)")]

    def val(base, share, effect):
        r = rng[rng.base.str.startswith(base) & (rng.car_share == share) & (rng.effect == effect)]
        return float(r.co2_t_central.iloc[0])

    for i, (sh, _) in enumerate(shares):
        lo, hi = val("A′", sh, "1년차 점추정"), val("A′", sh, "1년차 95% 상한")
        ext = val("서울 전 역", sh, "1년차 95% 상한")
        y = len(shares) - i
        ax.hlines(y, lo, hi, color=BLUE, lw=4.5, alpha=0.35)
        ax.hlines(y, hi, ext, color=BLUE, lw=0.8, ls=(0, (1.5, 1.5)))
        ax.plot([lo, hi], [y, y], "o", ms=4, color=BLUE, mec=SURFACE, mew=0.8, zorder=3)
        ax.plot(ext, y, "o", ms=4, color=SURFACE, mec=BLUE, mew=0.9, zorder=3)
        ax.annotate(f"{lo:,.0f} ~ {hi:,.0f} t  (전 역 외삽 상한 {ext:,.0f} t)", (lo, y), xytext=(0, 5),
                    textcoords="offset points", fontsize=FS_S, color=INK2, va="bottom")
    b_lo = bnd[bnd.car_share_of_lost == "25%"].co2_increase_t_central.iloc[0]
    b_hi = bnd[bnd.car_share_of_lost == "100%(극단)"].co2_increase_t_central.iloc[0]
    ax.hlines(0, b_lo, b_hi, color=ORANGE, lw=4.5, alpha=0.35)
    ax.plot([b_lo, b_hi], [0, 0], "o", ms=4, color=ORANGE, mec=SURFACE, mew=0.8, zorder=3)
    ax.annotate(f"+{b_lo:,.0f} ~ +{b_hi:,.0f} t (증가)", (b_lo, 0), xytext=(0, 5), textcoords="offset points",
                fontsize=FS_S, color=INK2, va="bottom")
    ax.axvline(21600, color=INK2, lw=0.8)
    ax.text(21600 * 1.06, -0.55, "서울시 발표\n연 약 21,600 t", fontsize=FS_S, color=INK2, va="bottom")
    ax.set_xscale("log")
    ax.set_xlim(30, 200000)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.set_ylim(-0.6, len(shares) + 0.6)
    ax.set_yticks([0] + list(range(len(shares), 0, -1)),
                  ["경계 이탈분의 25~100%가\n승용차로 갔다면(역효과)"] + [lab for _, lab in shares],
                  fontsize=FS, color=INK2)
    ax.set_xlabel("연간 CO2 변화 (t, 로그 눈금) — 파랑: 절감, 주황: 증가 가능", fontsize=FS, color=INK2, labelpad=2)
    save(fig, "fig4_carbon.png")


def main() -> None:
    plt.rcParams.update({"font.family": "NanumGothic", "axes.unicode_minus": False})
    fig1()
    fig2()
    fig3()
    fig4()


if __name__ == "__main__":
    main()
